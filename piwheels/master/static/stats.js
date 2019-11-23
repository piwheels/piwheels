function showContents() {
  var elements = [
    ['num-packages', showText, numberWithCommas],
    ['num-versions', showText, numberWithCommas],
    ['num-wheels', showText, numberWithCommas],
    ['downloads-day', showText, numberWithCommas],
    ['downloads-week', showText, numberWithCommas],
    ['downloads-month', showText, numberWithCommas],
    ['downloads-year', showText, numberWithCommas],
    ['downloads-all', showText, numberWithCommas],
    ['downloads-bandwidth', showText, doNothing],
    ['top-10-packages-month', showTable, doNothing],
    ['top-30-packages-all', showTable, doNothing],
    ['time-saved-day', showText, doNothing],
    ['time-saved-week', showText, doNothing],
    ['time-saved-month', showText, doNothing],
    ['time-saved-year', showText, doNothing],
    ['time-saved-all', showText, doNothing],
    ['energy-saved-all', showText, formatEnergy],
    ['updated', showText, doNothing],
    ['downloads-by-month', showBarChart, null],
    ['downloads-by-day', showBarChart, null],
    ['time-saved-by-month', showBarChart, null],
    ['python-versions-by-month', showLineChart, null],
    ['arch-by-month', showLineChart, null],
    ['os-by-month', showLineChart, null],
    ['raspbian-versions-by-month', showLineChart, null],
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

function showTable(id, data, fn) {
  var table = document.getElementById(id);
  var id = id.replace(/-/g, '_');
  var tbody = document.createElement('tbody');
  var packages = data[id];
  var i = 0;
  for (var p in packages) {
    i++;
    var pkg = packages[p];
    var row = document.createElement('tr');
    var td1 = document.createElement('td');
    var th = document.createElement('th');
    var td2 = document.createElement('td');
    var a = document.createElement('a');
    var link = '/project/' + pkg[0];
    var downloads = numberWithCommas(pkg[1]);
    td1.appendChild(document.createTextNode(i + '.'));
    a.appendChild(document.createTextNode(pkg[0]));
    a.setAttribute('href', link);
    th.appendChild(a);
    td2.appendChild(document.createTextNode(downloads));
    row.appendChild(td1);
    row.appendChild(th);
    row.appendChild(td2);
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
}

function showBarChart(id, data, fn) {
  var key = id.replace(/-/g, '_');
  var data = data[key];
  var keys = [];
  var values = [];
  for (var i in data) {
    var k = data[i][0];
    var v = data[i][1];
    keys.push(k);
    values.push(v);
  }

  var chart = [
    {
      'x': keys,
      'y': values,
      type: 'bar'
    }
  ];

  Plotly.newPlot(id, chart);
}

function showLineChart(id, data, fn) {
  var key = id.replace(/-/g, '_');
  var data = data[key];
  var chartData = [];

  for (var i in data) {
    var version = data[i][0];
    var keys = [];
    var values = [];
    for (var j in data[i][1]) {
      var key = data[i][1][j][0];
      var value = data[i][1][j][1];
      keys.push(key);
      values.push(value);
    }
    line = {
      'x': keys,
      'y': values,
      'mode': 'lines',
      'name': version
    }
    console.log(line)
    chartData.push(line);
  }

  Plotly.newPlot(id, chartData);
}

function numberWithCommas(n) {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function doNothing(s) {
  return s;
}

function formatEnergy(s) {
  return s.toString() + ' kWh';
}
