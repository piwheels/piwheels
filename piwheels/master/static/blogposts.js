const months = [
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
];

const formatDate = date => {
  const day = date.getDate();
  const month = months[date.getMonth()];
  const year = date.getFullYear();
  return `${day} ${month} ${year}`;
};

const htmlDecode = input => {
  const e = document.createElement('div');
  e.innerHTML = input;
  return e.childNodes.length === 0 ? "" : e.childNodes[0].nodeValue;
};

const showBlogPosts = (blogUrl, n) => {
  const ul = document.getElementById('latest-blog-posts');
  const blogJsonUrl = `${blogUrl}/wp-json/wp/v2/posts/?per_page=${n}`;

  fetch(blogJsonUrl)
    .then(response => response.json())
    .then(data => {
      ul.innerHTML = '';
      data.forEach(post => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        const postDate = new Date(post.date);
        const postDateText = document.createTextNode(` (${formatDate(postDate)})`);
        const title = htmlDecode(post.title.rendered);
        a.appendChild(document.createTextNode(title));
        a.setAttribute('href', post.link);
        li.appendChild(a);
        li.appendChild(postDateText);
        ul.appendChild(li);
      });
    })
    .catch(error => {
      const msg = 'Failed to load blog posts';
      console.error(msg, error);
      ul.innerHTML = `<li>${msg}</li>`;
    });
};

window.onload = () => {
  const blogUrl = "https://blog.piwheels.org";
  const numPosts = 10;
  showBlogPosts(blogUrl, numPosts);
};
