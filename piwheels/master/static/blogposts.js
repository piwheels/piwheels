var months = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec'
]

function dateFormat(date) {
  var day = date.getDate();
  var month = months[date.getMonth()];
  var year = date.getFullYear();
  return day + " " + month + " " + year;
}

function showBlogPosts(blogUrl, n) {
  var ul = document.getElementById('latest-blog-posts');
  var blogJsonUrl = blogUrl + "/wp-json/wp/v2/posts";
  var params = {
    'per_page': n
  };

  $.getJSON(blogJsonUrl, params)
    .fail(function() {
      console.error('Failed to load blog posts');
      ul.childNodes[0].textContent = "???";
    })
    .done(function(data) {
      ul.removeChild(ul.childNodes[0]);
      for (var p in data) {
        post = data[p];
        var li = document.createElement('li');
        var a = document.createElement('a');
        var postDate = new Date(post.date);
        var postDateText = document.createTextNode(" (" + dateFormat(postDate) + ")");
        a.appendChild(document.createTextNode(post.title.rendered));
        a.setAttribute('href', post.link);
        li.appendChild(a);
        li.appendChild(postDateText);
        ul.appendChild(li);
      }
    })
}
