document.addEventListener('DOMContentLoaded', () => {
  const addBtn = document.getElementById('add-walkin-row');
  const container = document.getElementById('walkin-items');
  if (addBtn && container) {
    addBtn.addEventListener('click', () => {
      const first = container.querySelector('.walkin-row');
      if (!first) return;
      const clone = first.cloneNode(true);
      clone.querySelector('select').value = '';
      clone.querySelector('input[name="quantity"]').value = '1';
      container.appendChild(clone);
    });
  }
});
