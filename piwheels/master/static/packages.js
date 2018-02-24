(function() {
    var packages = Array();
    var packageInput = $("form input");
    var packagesOutput = $("#packages");
    var status = $("#status");

    function item(pkg) {
      const li = document.createElement('li');
      const a = document.createElement('a');
      li.appendChild(a);
      a.href = "simple/" + pkg.name + "/";
      a.appendChild(document.createTextNode(pkg.name));
      return li;
    }

    packageInput.on("input", function(evt) {
      try {
        var searchFor = RegExp(evt.target.value, "i");
      }
      catch (e) {
        status.text("Invalid regular expression");
        return;
      }

      packagesOutput.empty();
      if (evt.target.value.length > 1) {
        var found = packages.filter(pkg => pkg.name.match(searchFor) !== null);
        found.sort(function(a, b) {
          const result = b.count - a.count;
          if (result) return result;
          return a.name.localeCompare(b.name);
        });
        packagesOutput.append(found.slice(0, 100).map(item));
        if (found.length > 100) packagesOutput.append("<li>&hellip;</li>");
        status.text((found.length > 100 ? ">100" : found.length) + " items found");
      }
      else {
        status.text("Enter at least 2 characters to begin search");
      }
    });

    $.getJSON("packages.json")
      .fail(function() {
        status.text("Failed to load package list");
      })
      .done(function(data) {
        packages = data;
        packageInput.removeAttr("disabled");
        status.text("Loaded package list (" + packages.length + " items)");
      });
})();
