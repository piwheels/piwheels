const showHiddenRows = className => {
  const rows = document.getElementsByClassName(className);
  while (rows.length > 0) {
    let row = rows[0];
    row.classList.remove(className);
  }
  const showMore = document.getElementById(`show-${className}s`);
  showMore.classList.add('hidden-version');
};

const numberWithCommas = n => {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
};

const showDownloads = package => {
  const downloadsAll = document.getElementById('downloads-all');
  const downloads30 = document.getElementById('downloads-30');
  fetch("/packages.json")
  .then(response => response.json())
  .then(packages => {
    const pkgInfo = packages.filter(pkg => pkg[0] === package)[0];
    downloadsAll.textContent = numberWithCommas(pkgInfo[2]);
    downloads30.textContent = numberWithCommas(pkgInfo[1]);
  })
  .catch(error => {
    console.error('Failed to load package info', error);
    downloadsAll.textContent = 'failed to load';
    downloads30.textContent = 'failed to load';
  });
};

const getIssues = package => {
  const url = 'https://api.github.com/repos/piwheels/packages/issues';
  const params = {
    per_page: 100,
    sort: 'created'
  };
  fetch(url, params)
  .then(r => r.json())
  .then(issues => issues.filter(issue =>
      issue.title.toLowerCase()
      .includes(package.toLowerCase())
  ))
  .then(issues => {
    showIssues(issues);
    const btn = document.getElementById('search-btn');
    btn.setAttribute('disabled', true);
  })
  .catch(error => {
    console.log('Failed to retrieve issues from github');
    const div = document.getElementById('issues');
    const h4 = document.createElement('h4');
    h4.innerHTML = 'Issues';
    const p = document.createElement('p');
    const a = document.createElement('a');
    const link = `https://github.com/piwheels/packages/issues?q=is%3Aissue+${package}+is%3Aopen`;
    a.setAttribute('href', link);
    a.innerHTML = 'GitHub';
    p.innerHTML = 'Failed to retrieve issues from ';
    p.appendChild(a);
    p.innerHTML += '.';
    div.appendChild(h4);
    div.appendChild(p);
  });
};

const showIssues = issues => {
  const div = document.getElementById('issues');
  const ul = document.createElement('ul');
  if (issues.length > 0) {
    const h4 = document.createElement('h4');
    h4.innerHTML = issues.length > 1
      ? `${issues.length} issues found`
      : '1 issue found';
    issues.map(issue => {
      let li = document.createElement('li');
      let a = document.createElement('a');
      a.setAttribute('href', issue.html_url);
      a.innerHTML = `#${issue.number} ${issue.title}`;
      li.appendChild(a);
      ul.appendChild(li);
    });
    div.appendChild(h4);
    div.appendChild(ul);
  } else {
    div.innerHTML = '<h4>No issues found</h4><p>Consider opening one.</p>';
  }
};
