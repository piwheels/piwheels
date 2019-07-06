(function() {
    var packages = Array();
    var packageInput = $("form input");
    var packagesOutput = $("#packages");
    var status = $("#status");
    
    function numberWithCommas(n) {
      return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    }

    function item(pkg) {
        const li = document.createElement('li');
        const a = document.createElement('a');
        li.appendChild(a);
        a.href = "project/" + pkg[0] + "/";
        a.appendChild(document.createTextNode(pkg[0]));
        return li;
    }

    packageInput.on("input", function(evt) {
        packagesOutput.empty();

        try {
            var searchFor = RegExp(evt.target.value, "i");
        }
        catch (e) {
            status.text("Invalid regular expression");
            return;
        }

        if (evt.target.value.length > 1) {
            var found = packages.filter(pkg => pkg[0].match(searchFor) !== null);
            found.sort(function(a, b) {
                /* Sort first on download count (on the basis more popular
                 * packages are more likely to be wanted), then alphabetically
                 */
                const result = b[1] - a[1];
                if (result) return result;
                return a[0].localeCompare(b[0]);
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
            status.text("Loaded package list (" + numberWithCommas(packages.length) + " items)");
        });
})();
