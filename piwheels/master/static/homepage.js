function showContents() {
  var elements = [
    ['num-packages', showText, numberWithCommas],
    ['num-wheels', showText, numberWithCommas],
    ['downloads-month', showText, numberWithCommas],
    ['downloads-all', showText, numberWithCommas],
    ['updated', showText, doNothing],
  ];
  $.getJSON("/statistics.json")
    .fail(function() {
      console.error("Failed to load statistics.json");
      for (var e in elements) {
        var element = document.getElementById(elements[e][0]);
        element.textContent = '???';
      }
    })
    .done(function(data) {
        for (var e in elements) {
          var id = elements[e][0];
          var showFunction = elements[e][1];
          var formatFunction = elements[e][2];
          showFunction(id, data, formatFunction);
        }
    })
}

function showText(id, data, fn) {
  var element = document.getElementById(id);
  var id = id.replace(/-/g, '_');
  element.textContent = fn(data[id]);
}

function numberWithCommas(n) {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function doNothing(s) {
  return s;
}
