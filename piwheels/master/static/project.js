const showHiddenRows = (className) => {
  const rows = document.getElementsByClassName(className);
  while (rows.length > 0) {
    let row = rows[0];
    row.classList.remove(className);
  }
  const showMore = document.getElementById(`show-${className}s`);
  showMore.classList.add('hidden-version');
};

const numberWithCommas = (n) => {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
};

const showDownloads = (package) => {
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
