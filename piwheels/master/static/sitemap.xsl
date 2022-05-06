<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="2.0"
  xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:map="http://www.sitemaps.org/schemas/sitemap/0.9">

  <xsl:output method="html" indent="yes" encoding="UTF-8"/>

  <xsl:template match="/">
  <html>
    <head>
      <title>piwheels - Sitemap<xsl:if test="map:sitemapindex"> Index</xsl:if></title>
      <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto" />
      <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto+Condensed" />
      <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto+Mono" />
      <link rel="stylesheet" href="/styles.css" />
    </head>
    <body>
      <header>
        <a class="logo" href="/"><div></div><h1>piwheels</h1></a>
        <nav>
          <a href="/packages.html">Search</a>
          <a href="/faq.html">FAQ</a>
          <a href="/json.html">API</a>
          <a href="https://blog.piwheels.org/">Blog</a>
        </nav>
      </header>


      <article>
        <section>
          <div class="content">
            <h2>Sitemap</h2>

              <p>This page is only intended for robots. If you are a human, you're
                probably in the wrong place and might find it more useful to click
                on the big logo at the top there!</p>
            </div>
        </section>

        <xsl:apply-templates/>

      </article>

      <footer>
        <nav>
          <a id="github" href="https://github.com/piwheels"><div></div>GitHub</a>
          <a id="readthedocs" href="https://piwheels.readthedocs.io/"><div></div>Docs</a>
          <a id="twitter" href="https://twitter.com/piwheels"><div></div>Twitter</a>
        </nav>
        <p class="notices">piwheels is a community project by
          <a href="https://twitter.com/ben_nuttall">Ben Nuttall</a>
          and <a href="https://twitter.com/waveform80">Dave Jones</a>.
          Powered by the <a href="https://www.mythic-beasts.com/order/rpi">Mythic
          Beasts Pi Cloud</a>.</p>
        <a id="mythic" href="https://www.mythic-beasts.com/"></a>
      </footer>
      
    </body>
  </html>
  </xsl:template>

  <xsl:template match="map:sitemapindex">
  <div class="row">
    <div class="small-12 columns">
      <table>
        <thead>
          <tr>
            <th>URL</th>
            <xsl:if test="map:sitemap/map:lastmod">
            <th>Last Modified</th>
            </xsl:if>
          </tr>
        </thead>
        <tbody>
        <xsl:for-each select="map:sitemap">
          <tr>
            <xsl:apply-templates select="map:loc"/>
            <xsl:apply-templates select="map:lastmod"/>
          </tr>
        </xsl:for-each>
        </tbody>
      </table>
    </div>
  </div>
  </xsl:template>

  <xsl:template match="map:urlset">
  <div class="row">
    <div class="small-12 columns">
      <table>
        <thead>
          <tr>
            <th>URL</th>
            <xsl:if test="map:url/map:changefreq">
            <th>Updated</th>
            </xsl:if>
            <xsl:if test="map:url/map:priority">
            <th>Priority</th>
            </xsl:if>
            <xsl:if test="map:url/map:lastmod">
            <th>Last Modified</th>
            </xsl:if>
          </tr>
        </thead>
        <tbody>
        <xsl:for-each select="map:url">
          <tr>
            <xsl:apply-templates select="map:loc"/>
            <xsl:apply-templates select="map:changefreq"/>
            <xsl:apply-templates select="map:priority"/>
            <xsl:apply-templates select="map:lastmod"/>
          </tr>
        </xsl:for-each>
        </tbody>
      </table>
    </div>
  </div>
  </xsl:template>

  <xsl:template match="map:loc">
  <td><a href="{.}"><xsl:apply-templates/></a></td>
  </xsl:template>

  <xsl:template match="map:changefreq|map:priority">
  <td><xsl:apply-templates/></td>
  </xsl:template>

  <xsl:template match="map:lastmod">
  <td><xsl:value-of select="concat(substring(., 0, 11), ' ', substring(., 12, 5))"/></td>
  </xsl:template>
</xsl:stylesheet>
