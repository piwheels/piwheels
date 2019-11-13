function showContents() {
  var numPackages = document.getElementById('num-packages');
  var numFiles = document.getElementById('num-files');
  var downloadsAll = document.getElementById('downloads-all');
  var downloads30 = document.getElementById('downloads-30');
  var updated = document.getElementById('updated');
  $.getJSON("/statistics.json")
    .fail(function() {
      console.error("Failed to load statistics.json");
      var elements = [numPackages, numFiles, downloadsAll, downloads30, updated];
      showErrors(elements);
    })
    .done(function(data) {
      numPackages.textContent = numberWithCommas(data.num_packages);
      numFiles.textContent = numberWithCommas(data.num_files);
      downloadsAll.textContent = numberWithCommas(data.downloads_all);
      downloads30.textContent = numberWithCommas(data.downloads_last_month);
      updated.textContent = data.updated;
    })
}

function showErrors(elements) {
  for (var e in elements) {
    elements[e].textContent = '???';
  }
}

function numberWithCommas(n) {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
