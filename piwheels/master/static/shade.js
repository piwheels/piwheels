/* Based on the fine article at
 * <https://css-tricks.com/using-css-transitions-auto-dimensions/> */

function shadeElement(el) {
  let innerHeight = el.scrollHeight;
  let oldTransition = el.style.transition;
  el.style.transition = '';
  requestAnimationFrame(function() {
    el.style.height = `${innerHeight}px`;
    el.style.transition = oldTransition;
    requestAnimationFrame(function() {
      el.style.height = '0';
      el.classList.add('shaded');
    });
  });
}

function unshadeElement(el) {
  function autoHeight(ev) {
    el.removeEventListener('transitionend', autoHeight);
    el.style.height = 'auto';
    el.classList.remove('shaded');
  }
  let innerHeight = el.scrollHeight;
  el.style.height = `${innerHeight}px`;
  el.addEventListener('transitionend', autoHeight);
}
