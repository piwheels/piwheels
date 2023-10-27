(function() {
  function showHiddenVersions() {
    /* Move the key beneath the table
     */
    const releasesDiv = document.querySelector('#releases').parentElement;
    const issuesHeader = document.querySelector('#issues');
    const keyHeader = document.querySelector('#key');
    const keyList = document.querySelector('#key ~ table');
    const keyDiv = keyHeader.parentElement;

    issuesHeader.before(keyHeader, keyList);
    keyDiv.remove();
    releasesDiv.classList.add('no-sidebar');

    /* Show all the release rows and hide the "Show all releases" link
     */
    const tableBody = document.querySelector('#releases ~ table tbody');

    for (const row of tableBody.querySelectorAll('tr'))
      row.classList.remove('hidden');
    tableBody.lastElementChild.remove();
  }

  function numberWithCommas(n) {
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function escapeForRegExp(s) {
    /* From MDN:
     * https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Regular_Expressions#escaping
     */
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function getIssues(ev) {
    const package = document.getElementById('package').dataset.package;
    const packageFilter = RegExp('\\b' + escapeForRegExp(package) + '\\b', 'i');
    const url = 'https://api.github.com/repos/piwheels/packages/issues';

    fetch(url)
      .then(r => r.json())
      .then(issues => issues.filter(issue => issue.title.match(packageFilter)))
      .then(showIssues)
      .catch(showIssuesFailed)
  }

  function showIssues(issues) {
    const issuesItem = document.querySelector('#issues ~ ul li:first-child');
    const issuesList = document.createElement('ul');
    let existingList;

    if (issues.length > 0) {
      issues.forEach(issue => {
        const issueItem = document.createElement('li');
        const issueLink = document.createElement('a');
        issueLink.href = issue.html_url;
        issueLink.text = `#${issue.number} ${issue.title}`;
        issueItem.append(issueLink);
        issuesList.append(issueItem);
      });
    } else {
      const issueItem = document.createElement('li');
      issueItem.textContent = 'No issues found';
      issuesList.append(issueItem);
    }
    if (existingList = issuesItem.querySelector('ul'))
      existingList.replaceWith(issuesList)
    else
      issuesItem.append(issuesList);
  }

  function showIssuesFailed(error) {
    const package = document.getElementById('package').dataset.package;
    const issuesItem = document.querySelector('#issues ~ ul li:first-child');
    const errorList = document.createElement('ul');
    let existingList;

    console.log('Failed to retrieve issues from github');
    errorList.innerHTML = `<li>Failed to retrieve issues from <a href="https://github.com/piwheels/packages/issues?q=is:issue+is:open+${package}">GitHub</a></li>`;
    if (existingList = issuesItem.querySelector('ul'))
      existingList.replaceWith(errorList)
    else
      issuesItem.append(errorList);
  }

  function showInstall(ev) {
    const install = document.querySelector('#install');
    const pre = document.querySelector('#install + p + pre');
    const project = document.getElementById('package').textContent;
    const dependencies = this.parentNode.dataset.dependencies;
    const version = this
      .parentElement
      .parentElement
      .parentElement
      .parentElement
      .previousElementSibling
      .firstElementChild
      .textContent
      .trim();

    let commands = `pip3 install ${project}==${version}`;
    if (dependencies.length)
      commands = `sudo apt install ${dependencies}\r\n` + commands;
    pre.textContent = commands;
    install.scrollIntoView({behavior: "smooth"});
  }

  function toggleShade(ev) {
    if (!('files' in this)) return;
    if (this.files.classList.contains('shaded')) {
      unshadeElement(this.files);
      this.parentElement.classList.remove('expandable');
      this.parentElement.classList.add('collapsible');
    }
    else {
      shadeElement(this.files);
      this.parentElement.classList.add('expandable');
      this.parentElement.classList.remove('collapsible');
    }
    ev.stopPropagation();
  }

  window.addEventListener('load', function(ev) {
    /* Load the download counters asynchronously in the background
     */
    const package = document.getElementById('package').dataset.package;
    const downloadsAll = document.getElementById('downloads-all');
    const downloadsRecent = document.getElementById('downloads-30');

    fetch("/packages.json")
      .then(response => response.json())
      .then(packages => {
        const pkgInfo = packages.filter(pkg => pkg[0] === package)[0];

        downloadsAll.textContent = numberWithCommas(pkgInfo[2]);
        downloadsRecent.textContent = numberWithCommas(pkgInfo[1]);
      })
      .catch(error => {
        console.error('Failed to load package info', error);
        downloadsAll.textContent = 'failed to load';
        downloadsRecent.textContent = 'failed to load';
      });

    /* Hide all file lists and set up expansion buttons
     */
    for (const filesList of document.querySelectorAll('#releases ~ table ul')) {
      if (filesList.children.length) {
        const filesCell = filesList
          .parentElement
          .parentElement
          .previousElementSibling
          .lastElementChild;
        const icon = filesCell.appendChild(document.createElement('div'));

        filesCell.classList.add('expandable');
        filesList.classList.add('shaded');
        icon.files = filesList;
        icon.addEventListener('click', toggleShade);
        for (const fileLink of filesList.querySelectorAll('li')) {
          installLink = document.createElement('span');
          installLink.classList.add('install');
          installLink.classList.add('button');
          installLink.textContent = 'How to install this version';
          installLink.addEventListener('click', showInstall);
          fileLink.appendChild(installLink);
        }
      }
    }

    /* Hide everything beyond the latest five versions released and add an
     * expand action at the end of the table
     */
    const versionsTable = document.querySelector('#releases + table tbody');

    if (versionsTable.children.length > 10) {
      for (let i = 0; i < versionsTable.children.length; ++i)
        if (i > 11) versionsTable.children[i].classList.add('hidden');
      expand = document.createElement('tr');
      expand.classList.add('more');
      const colCount = document.querySelectorAll(
        '#releases + table thead tr th').length;
      expand.innerHTML = `<td colspan="${colCount}">Show all releases</td>`;
      expand.addEventListener('click', showHiddenVersions);
      versionsTable.appendChild(expand);
    }

    /* Convert the search issues link to a javascript action
     */
    issuesLink = document.querySelector('#issues ~ ul li:first-child a');
    issuesLink.removeAttribute('href');
    issuesLink.onclick = getIssues;
  });
})();
