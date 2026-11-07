"""Перевірка основних сценаріїв і прав доступу без зміни робочої бази."""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.database = str(Path(self.folder.name) / 'test.db')
        self.app = create_app({'TESTING': True, 'DATABASE': self.database,
                               'INSTANCE_PATH': self.folder.name, 'SECRET_KEY': 'test-secret'})
        self.client = self.app.test_client()

    def tearDown(self):
        self.folder.cleanup()

    def post(self, client, path, data=None):
        client.get('/')
        with client.session_transaction() as state:
            token = state['csrf_token']
        return client.post(path, data={**(data or {}), 'csrf_token': token}, follow_redirects=True)

    def register(self, client, email='writer@example.com'):
        return self.post(client, '/register', dict(name='Тестовий автор', email=email,
                         password='TestPass123', confirm_password='TestPass123'))

    def article(self, client, status='published', title='Стаття про цифрову культуру'):
        return self.post(client, '/articles/new', dict(title=title, summary='Короткий опис тестової статті.',
                         content='Це змістовний текст для перевірки публікації. ' * 8,
                         category='Технології', cover='sage', status=status))

    def query(self, sql, params=()):
        with closing(sqlite3.connect(self.database)) as conn:
            return conn.execute(sql, params).fetchall()

    def test_registration_password_hash_login_logout_and_duplicate_email(self):
        response = self.register(self.client)
        self.assertEqual(response.status_code, 200)
        row = self.query('SELECT password_hash FROM users')[0]
        self.assertNotEqual(row[0], 'TestPass123')
        self.post(self.client, '/logout')
        self.post(self.client, '/login', dict(email='writer@example.com', password='wrong'))
        with self.client.session_transaction() as state:
            self.assertNotIn('user_id', state)
        self.post(self.client, '/login', dict(email='writer@example.com', password='TestPass123'))
        with self.client.session_transaction() as state:
            self.assertEqual(state['user_id'], 1)
        self.post(self.client, '/logout')
        self.register(self.client, 'WRITER@example.com')
        self.assertEqual(len(self.query('SELECT id FROM users')), 1)

    def test_article_lifecycle_and_draft_visibility(self):
        self.register(self.client)
        self.assertEqual(self.article(self.client, status='draft').status_code, 200)
        self.assertEqual(self.app.test_client().get('/articles/1').status_code, 404)
        data = dict(title='Оновлений заголовок статті', summary='Опис статті після оновлення.',
                    content='Змістовний текст статті після редагування. ' * 5,
                    category='Культура', cover='peach', status='published')
        self.assertEqual(self.post(self.client, '/articles/1/edit', data).status_code, 200)
        self.assertEqual(self.app.test_client().get('/articles/1').status_code, 200)
        self.post(self.client, '/articles/1/delete')
        self.assertEqual(self.client.get('/articles/1').status_code, 404)

    def test_other_author_cannot_edit_delete_or_read_draft(self):
        self.register(self.client)
        self.article(self.client)
        self.article(self.client, status='draft')
        other = self.app.test_client()
        self.register(other, 'other@example.com')
        self.assertEqual(other.get('/articles/1/edit').status_code, 403)
        self.assertEqual(self.post(other, '/articles/1/delete').status_code, 403)
        self.assertEqual(other.get('/articles/2').status_code, 404)
        self.assertEqual(len(self.query('SELECT id FROM articles')), 2)

    def test_comments_bookmarks_and_cascade_delete(self):
        self.register(self.client)
        self.article(self.client)
        self.post(self.client, '/articles/1/comments', {'content': 'Корисна стаття!'})
        self.assertEqual(len(self.query('SELECT id FROM comments')), 1)
        self.post(self.client, '/articles/1/bookmark')
        self.assertIn('Стаття про'.encode(), self.client.get('/saved').data)
        self.post(self.client, '/articles/1/bookmark')
        self.assertFalse(self.query('SELECT * FROM bookmarks'))
        self.post(self.client, '/articles/1/bookmark')
        other = self.app.test_client()
        self.register(other, 'reader@example.com')
        self.assertEqual(self.post(other, '/comments/1/delete').status_code, 403)
        self.post(self.client, '/articles/1/delete')
        self.assertFalse(self.query('SELECT * FROM comments'))
        self.assertFalse(self.query('SELECT * FROM bookmarks'))

    def test_search_ukrainian_casefold_categories_and_pagination(self):
        self.register(self.client)
        for i in range(7):
            self.article(self.client, title=f'ЦИФРОВА КУЛЬТУРА номер {i}')
        html = self.client.get('/?q=цифрова+культура').get_data(as_text=True)
        self.assertIn('7 публікацій', html)
        self.assertIn('Сторінки статей', html)
        self.assertNotIn('ЦИФРОВА КУЛЬТУРА номер 0', html)
        self.assertIn('ЦИФРОВА КУЛЬТУРА номер 0', self.client.get('/?page=2').get_data(as_text=True))
        self.assertIn('Поки що тихо', self.client.get('/?category=Культура').get_data(as_text=True))
        self.assertEqual(self.client.get('/?page=-10&sort=invalid').status_code, 200)

    def test_validation_csrf_authentication_and_html_escaping(self):
        self.assertEqual(self.client.get('/cabinet').status_code, 302)
        self.client.get('/')
        self.assertEqual(self.client.post('/register', data={'name': 'Автор'}).status_code, 400)
        self.assertEqual(self.client.post('/register', data={'csrf_token': 'fake'}).status_code, 400)
        self.register(self.client)
        invalid = dict(title='A', summary='B', content='C', cover='sage', category='Культура', status='published')
        self.post(self.client, '/articles/new', invalid)
        self.assertFalse(self.query('SELECT id FROM articles'))
        result = self.article(self.client, title='<script>alert(1)</script>')
        self.assertIn(b'&lt;script&gt;', result.data)
        self.assertNotIn(b'<script>alert(1)</script>', result.data)
        result = self.post(self.client, '/articles/1/comments', {'content': '<script>alert(2)</script>'})
        self.assertNotIn(b'<script>alert(2)</script>', result.data)
        self.assertIn(b'&lt;script&gt;alert(2)', result.data)

    def test_public_blog_contains_only_published_articles_and_no_email(self):
        self.register(self.client)
        self.article(self.client, title='Публічна стаття автора')
        self.article(self.client, status='draft', title='Приватна чернетка автора')
        visitor = self.app.test_client()
        response = visitor.get('/authors/1')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Публічна стаття автора', html)
        self.assertNotIn('Приватна чернетка автора', html)
        self.assertNotIn('writer@example.com', html)
        self.assertEqual(visitor.get('/authors/999').status_code, 404)

    def test_draft_comments_forbidden_and_profile_validation(self):
        self.register(self.client)
        self.article(self.client, status='draft')
        self.assertEqual(self.post(self.client, '/articles/1/comments', {'content': 'Коментар'}).status_code, 400)
        self.assertEqual(self.post(self.client, '/articles/1/bookmark').status_code, 400)
        self.post(self.client, '/profile', {'name': 'Нове ім’я', 'bio': 'Автор цікавих історій.'})
        self.assertEqual(self.query('SELECT name FROM users')[0][0], 'Нове ім’я')
        self.post(self.client, '/profile', {'name': 'X', 'bio': ''})
        self.assertEqual(self.query('SELECT name FROM users')[0][0], 'Нове ім’я')


if __name__ == '__main__':
    unittest.main()
