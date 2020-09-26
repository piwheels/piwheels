/* Based on the fine article at
 * <https://css-tricks.com/using-css-transitions-auto-dimensions/> */

function shadeElement(el) {
  let inner_height = el.scrollHeight;
  let old_transition = el.style.transition;
  el.style.transition = '';
  requestAnimationFrame(function() {
    el.style.height = `${inner_height}px`;
    el.style.transition = old_transition;
    requestAnimationFrame(function() {
      el.style.height = '0';
    });
  });
  el.dataset.shaded = 'true';
}

function unshadeElement(el) {
  function autoHeight(ev) {
    el.removeEventListener('transitionend', autoHeight);
    el.style.height = 'auto';
  }
  let innerHeight = el.scrollHeight;
  el.style.height = `${innerHeight}px`;
  el.addEventListener('transitionend', autoHeight);
  el.dataset.shaded = 'false';
}
