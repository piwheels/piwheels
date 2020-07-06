<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="2.0"
  xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:map="http://www.sitemaps.org/schemas/sitemap/0.9">

  <xsl:output method="html" indent="yes" encoding="UTF-8"/>

  <xsl:template match="/">
  <html>
    <head>
      <title>piwheels - Sitemap<xsl:if test="map:sitemapindex"> Index</xsl:if></title>
      <link rel="stylesheet" href="/foundation-float.min.css" />
      <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto" />
      <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto+Condensed" />
      <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto+Mono" />
      <link rel="stylesheet" href="/styles.css" />
    </head>
    <body>
      <header>
        <div class="row">
          <div class="title-bar" data-responsive-toggle="nav-menu" data-hide-for="medium">
            <button class="menu-icon" type="button" data-toggle="nav-menu"></button>
            <div class="title-bar-title">Menu</div>
          </div>

          <div class="top-bar" id="nav-menu">
            <div class="top-bar-left">
              <ul class="menu">
                <li class="menu-text">
                  <a href="/">
                    <div class="logo"></div>
                    <h1>piwheels</h1>
                  </a>
                </li>
              </ul>
            </div>
            <div class="top-bar-right">
              <ul class="menu">
                <li><a class="button" href="/packages.html">Packages</a></li>
                <li><a class="button" href="https://github.com/piwheels/packages/issues">Package Issues</a></li>
                <li><a class="button" href="/faq.html">FAQ</a></li>
                <li><a class="button" href="/stats.html">Stats</a></li>
                <li><a class="button" href="https://blog.piwheels.org/">Blog</a></li>
                <li><a class="button" href="https://github.com/piwheels">GitHub</a></li>
                <li><a class="button" href="https://piwheels.readthedocs.io/">Docs</a></li>
                <li><a class="button" href="https://twitter.com/piwheels">Twitter</a></li>
              </ul>
            </div>
          </div>
        </div>
      </header>

      <div class="row">
        <div class="small-12 columns">
          <h2>Sitemap</h2>

          <p>This page is only intended for robots. If you are a human, you're
            probably in the wrong place and might find it more useful to click
            on the big logo at the top there!</p>
        </div>
      </div>

      <xsl:apply-templates/>

      <footer>
        <div class="row">
          <div class="small-12 medium-8 columns">
            <p>piwheels is a community project by <a href="https://twitter.com/ben_nuttall">Ben Nuttall</a>
              and <a href="https://twitter.com/waveform80">Dave Jones</a>.
              Hosting is kindly donated by <a href="https://www.mythic-beasts.com/">Mythic Beasts</a>.
              Project <a href="https://github.com/piwheels/piwheels">source code</a> is available from GitHub.</p>
          </div>
          <div class="small-12 medium-4 columns">
            <a href="https://www.mythic-beasts.com/"><img src="/mythic_beasts_logo.png" /></a>
          </div>
        </div>
      </footer>
      <script src="//code.jquery.com/jquery-3.3.1.min.js"></script>
      <script src="/what-input.min.js"></script>
      <script src="/foundation.min.js"></script>
      <script>$(document).foundation();</script>
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
