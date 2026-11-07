import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Boulder Roller',
  titleTemplate: ':title · Docs · Boulder Roller',
  description: 'Boulder Roller docs: rides, climbs, leaderboards, CAL, DUNG, and Vaults.',
  srcExclude: ['README.md'],
  cleanUrls: true,

  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
    ['link', { rel: 'icon', type: 'image/png', sizes: '32x32', href: '/favicon-32.png' }]
  ],

  themeConfig: {
    nav: [
      { text: 'About', link: '/' },
      { text: 'Get started', link: '/getting-started/access' },
      { text: 'FAQ', link: '/reference/faq' },
      { text: 'Open climb data', link: '/open-data' },
      { text: 'App', link: 'https://app.boulderroller.xyz' }
    ],

    sidebar: [
      {
        text: 'About',
        items: [
          { text: 'About Boulder Roller', link: '/' }
        ]
      },
      {
        text: 'Get started',
        items: [
          { text: 'Access', link: '/getting-started/access' },
          { text: 'Create an account', link: '/getting-started/account' },
          { text: 'Upload a ride', link: '/getting-started/upload' },
          { text: 'iOS app', link: '/getting-started/ios' }
        ]
      },
      {
        text: 'Rides',
        items: [
          { text: 'What happens to a ride', link: '/rides/processing' },
          { text: 'Results', link: '/rides/results' },
          { text: 'CAL', link: '/rides/cal' },
          { text: 'Training', link: '/rides/training' },
          { text: 'Feed and following', link: '/rides/feed' },
          { text: 'Privacy and your data', link: '/rides/privacy' }
        ]
      },
      {
        text: 'Climbs',
        items: [
          { text: 'Climbs', link: '/climbs/climbs' },
          { text: 'Leaderboards', link: '/climbs/leaderboards' },
          { text: 'Local Legend', link: '/climbs/local-legend' },
          { text: 'Vaults', link: '/climbs/vaults' }
        ]
      },
      {
        text: 'DUNG',
        items: [
          { text: 'Settlement weeks', link: '/dung/settlement-weeks' },
          { text: 'Distribution', link: '/dung/distribution' },
          { text: 'Balance and wallet', link: '/dung/balance' },
          { text: 'Fees and minimums', link: '/dung/fees' }
        ]
      },
      {
        text: 'Reference',
        items: [
          { text: 'Glossary', link: '/reference/glossary' },
          { text: 'Open climb data', link: '/open-data' },
          { text: 'Geographic data exception', link: '/reference/terms' },
          { text: 'FAQ', link: '/reference/faq' }
        ]
      },
      {
        text: 'Support',
        items: [
          { text: 'Common issues', link: '/support/common-issues' },
          { text: 'Contact', link: '/support/contact' }
        ]
      }
    ],

    footer: {
      message: 'Boulder Roller docs',
      copyright: '© Boulder Roller'
    },

    search: {
      provider: 'local',
      options: {
        // Frozen per-release open-data pages repeat the landing page; keep them out of search.
        _render(src, env, md) {
          if (env.relativePath.startsWith('open-data/releases/')) return ''
          return md.render(src, env)
        }
      }
    }
  }
})
