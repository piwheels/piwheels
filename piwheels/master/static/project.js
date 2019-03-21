function showHiddenRows(className) {
  var rows = document.getElementsByClassName(className);
  while (rows.length > 0) {
    var row = rows[0];
    row.classList.remove(className);
  }
  var showMore = document.getElementById('show-' + className + 's');
  showMore.classList.add('hidden-version');
}

function numberWithCommas(n) {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function getDownloads(data, package) {
  for (var i=0; i<=data.length; i++) {
    var packageData = data[i];
    if (packageData[0] == package) {
      return packageData;
    }
  }
  return [package, 0, 0];
}

function showDownloads(package) {
  var downloadsAll = document.getElementById('downloads-all');
  var downloads30 = document.getElementById('downloads-30');
  $.getJSON("/packages.json")
    .fail(function() {
      downloadsAll.textContent = '???';
      downloads30.textContent = '???';
    })
    .done(function(data) {
      var downloads = getDownloads(data, package);
      downloadsAll.textContent = numberWithCommas(downloads[2]);
      downloads30.textContent = numberWithCommas(downloads[1]);
    })
}
