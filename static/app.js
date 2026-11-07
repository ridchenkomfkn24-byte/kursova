const menuButton = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#navigation');
menuButton?.addEventListener('click', () => {
  const expanded = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!expanded));
  navigation.classList.toggle('is-open', !expanded);
});

document.querySelectorAll('.dismiss').forEach(button => {
  button.addEventListener('click', () => button.closest('.notice').remove());
});

document.querySelectorAll('[data-password]').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.password);
    const reveal = input.type === 'password';
    input.type = reveal ? 'text' : 'password';
    button.setAttribute('aria-label', reveal ? 'Приховати пароль' : 'Показати пароль');
    button.setAttribute('aria-pressed', String(reveal));
  });
});

document.querySelector('#sort')?.addEventListener('change', event => event.target.form.requestSubmit());
document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

const editor = document.querySelector('#editor-form');
const content = document.querySelector('#article-content');
if (editor && content) {
  let changed = false;
  const updateCount = () => {
    const words = content.value.trim().split(/\s+/u).filter(Boolean).length;
    document.querySelector('#word-count').textContent = `${words} слів · приблизно ${Math.max(1, Math.ceil(words / 180))} хв читання`;
  };
  editor.addEventListener('input', () => { changed = true; updateCount(); });
  editor.addEventListener('change', () => { changed = true; });
  editor.addEventListener('submit', () => { changed = false; });
  window.addEventListener('beforeunload', event => {
    if (changed) { event.preventDefault(); event.returnValue = ''; }
  });
  updateCount();
}
