function join(arr, sep) {
  var str = '';
  for (var s in arr) {
    str += arr[s] + sep;
  }
  return str.substring(0, str.length - sep.length);
}

function numberWithCommas(n) {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function isEmpty(o) {
  for (var i in o) {
    return false;
  }
  return true;
}

function wordCount(str) {
  if (str.length == 0) {
    return 0;
  }
  return str.split(' ').length;
}

function addHeaderRow(tbody, headers) {
  var row = document.createElement('tr');
  for (var h in headers) {
    var th = document.createElement('th');
    th.appendChild(document.createTextNode(headers[h]));
    row.appendChild(th);
  }
  tbody.append(row);
}

function addShowMoreRow(tbody, tableName) {
  var text = 'Show more ' + tableName + 's';
  var id = 'show-hidden-' + tableName + 's';
  var cls = 'show-more';
  var onclick = "showHiddenRows('hidden-" + tableName + "')";
  var row = document.createElement('tr');
  var td = document.createElement('td');
  var a = document.createElement('a');
  row.setAttribute('id', id);
  row.setAttribute('class', cls);
  a.setAttribute('onclick', onclick);
  a.appendChild(document.createTextNode(text));
  td.appendChild(a);
  row.appendChild(td);
  tbody.append(row);
}

function addTd(row, data) {
  var td = document.createElement('td');
  if (data.a) {
    var a = document.createElement('a');
    a.appendChild(document.createTextNode(data.text));
    a.setAttribute('href', data.a);
    td.appendChild(a);
  }
  else {
    td.appendChild(document.createTextNode(data['text']));
  }
  if (data['tip']) {
    td.setAttribute('title', data.tip);
  }
  row.appendChild(td);
}

function addDependenciesTd(row, package, version, deps) {
  var td = document.createElement('td');
  var a = document.createElement('a');
  a.appendChild(document.createTextNode('show'));
  var onclick = "showInstall('" + package + "', '" + version + "', '" + deps + "')";
  a.setAttribute('onclick', onclick);
  td.appendChild(a);
  row.appendChild(td);
}

function showErrors(elements) {
  for (var e in elements) {
    elements[e].textContent = '???';
  }
}

function getData(package) {
  data = null;
  $.getJSON("/project/" + package + "/json")
    .done(function(d) {
      data = d;
  })
  return data;
}

function showContents(package) {
  var numVersions = document.getElementById('num-versions');
  var numFiles = document.getElementById('num-files');
  var updated = document.getElementById('updated');
  $.getJSON("/project/" + package + "/json")
    .fail(function() {
      console.error("Failed to load " + package + " JSON");
      var elements = [numVersions, numFiles, updated];
      showErrors(elements);
    })
    .done(function(data) {
      numVersions.textContent = data.num_versions;
      numFiles.textContent = data.num_files;
      updated.textContent = data.updated;
      showVersions(data.versions);
      showFiles(package, data.versions);
    })
  showDownloads(package);
}

function getABIs(vi, status) {
  var abis = [];
  for (var abi in vi.builds) {
    if (!isEmpty(vi.builds[abi][status])) {
      if (abi == 'none') {
        var sb = vi.builds.none.successful_builds;
        for (var tag in sb) {
          var builder_abi = sb[tag].builder_abi;
        }
        abi = builder_abi + '+';
      }
      abis.push(abi);
    }
  }
  abis.sort();
  return join(abis, ', ');
}

function addVersionRow(tbody, versions, v, i) {
  var row = document.createElement('tr');
  var vi = versions[v];
  var successful_builds = getABIs(vi, 'successful_builds');
  var failed_builds = getABIs(vi, 'failed_builds');
  var release_dt = vi.released;
  var release_date = release_dt.substring(0, 10);
  var cols = [
    {'text': v, 'a': null, 'tip': null},
    {'text': release_date, 'a': null, 'tip': release_dt},
    {'text': successful_builds, 'a': null, 'tip': null},
    {'text': failed_builds, 'a': null, 'tip': null},
    {'text': versions[v]['skip'], 'a': null, 'tip': null},
  ]
  for (var c in cols) {
    addTd(row, cols[c]);
  }
  if (i > 5) {
    row.setAttribute('class', 'hidden-version');
  }
  tbody.appendChild(row);
}

function addFileRows(tbody, package, versions) {
  var i = 1;
  for (var v in versions) {
    var vi = versions[v];
    var builds = vi.builds;
    for (var abi in builds) {
      var platforms = builds[abi].successful_builds;
      for (var p in platforms) {
        var platform = platforms[p];
        var row = document.createElement('tr');
        var deps = platform.apt_dependencies;
        if (!deps) {
          deps = '';
        }
        var cols = [
          {'text': v, 'a': null, 'tip': vi['released']},
          {'text': abi, 'a': null, 'tip': null},
          {'text': p, 'a': null, 'tip': null},
          {'text': platform['filename'], 'a': platform['url'], 'tip': null},
          {'text': platform['filesize_human'], 'a': null, 'tip': null},
        ]
        for (var c in cols) {
          addTd(row, cols[c]);
        }
        addDependenciesTd(row, package, v, deps);
        if (i == 1) {
          var noScroll = true;
          showInstall(package, v, deps, noScroll);
        }
        else if (i > 5) {
          row.setAttribute('class', 'hidden-file');
        }
        tbody.appendChild(row);
        i++;
      }
    }
  }
  if (i > 5) {
    addShowMoreRow(tbody, 'file');
  }
}

function showVersions(versions) {
  var versionsTable = document.getElementById('versions');
  var newTable = document.createElement('table');
  newTable.setAttribute('id', 'versions')
  var tbody = document.createElement('tbody');
  if (isEmpty(versions)) {
    newTable.setAttribute('class', 'empty');
    addHeaderRow(tbody, ['No versions']);
  }
  else {
    addHeaderRow(tbody, ['Version', 'Released', 'Successful builds', 'Failed builds', 'Skip']);
    var i = 1;
    for (var v in versions) {
      addVersionRow(tbody, versions, v, i);
      i++;
    }
    if (i > 5) {
      addShowMoreRow(tbody, 'version')
    }
  }
  newTable.appendChild(tbody);
  versionsTable.replaceWith(newTable);
}

function showFiles(package, versions) {
  var filesTable = document.getElementById('files');
  var newTable = document.createElement('table');
  newTable.setAttribute('id', 'files')
  var tbody = document.createElement('tbody');
  if (isEmpty(versions)) {
    newTable.setAttribute('class', 'empty');
    addHeaderRow(tbody, ['No files']);
  }
  else {
    addHeaderRow(tbody, ['Version', 'ABI', 'Platform', 'Filename', 'Size', 'Installation']);
    addFileRows(tbody, package, versions);
  }
  newTable.appendChild(tbody);
  filesTable.replaceWith(newTable);
}

function showHiddenRows(className) {
  var rows = document.getElementsByClassName(className);
  while (rows.length > 0) {
    var row = rows[0];
    row.classList.remove(className);
  }
  var showMore = document.getElementById('show-' + className + 's');
  showMore.classList.add('hidden-version');
}

function getDownloads(data, package) {
  for (var d in data) {
    var packageData = data[d];
    if (packageData[0] == package) {
      return packageData;
    }
  }
  console.error('Package not found in packages.json');
  return [package, 0, 0];
}

function showDownloads(package) {
  var downloadsAll = document.getElementById('downloads-all');
  var downloads30 = document.getElementById('downloads-30');
  $.getJSON("/packages.json")
    .fail(function() {
      console.error('Failed to load packages.json');
      elements = [downloadsAll, downloads30];
      showError(elements);
    })
    .done(function(data) {
      var downloads = getDownloads(data, package);
      downloadsAll.textContent = numberWithCommas(downloads[2]);
      downloads30.textContent = numberWithCommas(downloads[1]);
    })
}

function showInstall(package, version, deps, noScroll) {
  var installPre = document.getElementById('install');
  var pip = 'sudo pip3 install ' + package + '==' + version;
  var apt = '';
  var installCmd = pip;
  if (deps) {
    apt = 'sudo apt install ' + deps;
    installCmd = apt + '\n' + pip;
  }
  installPre.textContent = installCmd;
  if (!noScroll) {
    document.getElementById('install-header').scrollIntoView();
  }
}
