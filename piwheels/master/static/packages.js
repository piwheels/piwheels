(function() {
  let packages = Array();
  const packageInput = document.querySelector("form input");
  const packagesOutput = document.querySelector("#packages");
  const status = document.querySelector("#status");

  function numberWithCommas(n) {
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function projectLink(pkg) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    li.appendChild(a);
    a.setAttribute("href", `project/${pkg[0]}/`);
    a.textContent = pkg[0];
    return li;
  }

  packageInput.addEventListener("input", function(ev) {
    let searchFor = null;
    while (packagesOutput.firstChild)
      packagesOutput.removeChild(packagesOutput.firstChild);

    try {
      searchFor = RegExp(this.value);
    }
    catch (exc) {
      status.textContent = "Invalid regular expression";
      ev.stopPropagation();
      return;
    }

    if (this.value.length < 2)
      status.textContent = "Enter at least 2 characters to begin search";
    else {
      let found = packages
        .filter(pkg => pkg[0].match(searchFor) !== null)
        .sort(function(a, b) {
          const result = b[1] - a[1];
          if (result) return result;
          return a[0].localeCompare(b[0]);
        });
      found
        .slice(0, 100)
        .map(projectLink)
        .forEach(el => packagesOutput.appendChild(el));
      status.textContent = `${found.length > 100 ? ">100" : found.length} items found`;
      if (found.length > 100)
        packagesOutput.appendChild(document.createElement("li")).textContent = "…";
    }
    ev.stopPropagation();
  });

  let request = new XMLHttpRequest();
  request.open("GET", "packages.json", true);
  request.addEventListener("load", function() {
    if (200 <= this.status < 400) {
      packages = JSON.parse(this.response);
      packageInput.removeAttribute("disabled");
      status.textContent = `Loaded package list (${numberWithCommas(packages.length)} items)`;
    }
    else
      status.textContent = "Failed to load package list";
  });
  request.addEventListener("error", function() {
    status.textContent = "Failed to load package list";
  });
  request.send();
})();
