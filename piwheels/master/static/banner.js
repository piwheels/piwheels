const getIssues = () => {
  const url = 'https://api.github.com/repos/piwheels/packages/issues?labels=banner';

  fetch(url)
    .then(r => r.json())
    .then(showBanner);
};

const showBanner = (issues) => {
  if (issues.length) {
    const banner = document.getElementById('noticebar');
    const contents = banner.getElementsByClassName('contents')[0];
    issues.map(issue => {
      let p = document.createElement('p');
      let s = document.createElement('strong');
      s.textContent = "Notice: "
      let a = document.createElement('a');
      a.textContent = issue.title;
      a.href = issue.html_url;
      p.appendChild(s);
      p.appendChild(a);
      contents.appendChild(p);
    });
    banner.classList.remove('hidden');
  }
};

getIssues();