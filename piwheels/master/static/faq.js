(function() {
  function toggleShade(ev) {
    if (!('faq' in this)) return;
    if (this.faq.dataset.shaded === 'true') {
      unshadeElement(this.faq);
      this.classList.remove('expandable');
      this.classList.add('collapsible');
    }
    else {
      shadeElement(this.faq);
      this.classList.add('expandable');
      this.classList.remove('collapsible');
    }
    ev.stopPropagation();
  }

  window.addEventListener('load', function(ev) {
    const selected = document.querySelector('h5:target');
    for (let faq of document.querySelectorAll('h5 + div')) {
      let question = faq.previousElementSibling;
      let icon = question.insertAdjacentElement(
        'afterbegin', document.createElement('div'));
      question.faq = faq;
      faq.classList.add('shaded');
      if (question === selected) {
        faq.dataset.shaded = 'false';
        faq.style.height = 'auto';
        question.classList.add('collapsible');
      }
      else {
        faq.dataset.shaded = 'true';
        question.classList.add('expandable');
      }
      question.addEventListener('click', toggleShade);
      icon.addEventListener('click', toggleShade);
    }
    if (selected)
      selected.scrollIntoView();
  });
})();
