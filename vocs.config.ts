import { defineConfig } from 'vocs'

export default defineConfig({
  title: 'W3E Docs',
  description: 'Professional blockchain data infrastructure for traders, researchers, and builders',
  topNav: [
    { text: 'Website', link: 'https://web3engineering.co.uk/' },
    { text: 'Request Trial', link: 'https://forms.gle/b5Fuuns7jcA3nHKv5' },
    { text: 'Telegram', link: 'https://t.me/inventandchill' },
  ],
  sidebar: [
    { text: 'Introduction', link: '/' },
    {
      text: 'Solana Indexer',
      collapsed: false,
      items: [
        { text: 'Overview', link: '/solana/' },
        { text: 'Getting Started', link: '/solana/getting-started' },
        { text: 'Query Examples', link: '/solana/examples' },
        { text: 'Table Reference', link: '/solana/tables' },
      ],
    },
    {
      text: 'HyperLiquid Indexer',
      collapsed: false,
      items: [
        { text: 'Overview', link: '/hyperliquid/' },
        { text: 'Query Examples', link: '/hyperliquid/examples' },
        { text: 'Table Reference', link: '/hyperliquid/tables' },
      ],
    },
    {
      text: 'Polymarket Indexer',
      collapsed: false,
      items: [
        { text: 'Overview', link: '/polymarket/' },
        { text: 'Query Examples', link: '/polymarket/examples' },
        { text: 'Table Reference', link: '/polymarket/tables' },
      ],
    },
    {
      text: 'Geyser Node',
      link: '/geyser',
    },
    {
      text: 'Axiom API',
      link: '/axiom-api',
    },
    {
      text: 'Services',
      collapsed: true,
      items: [
        { text: 'Overview', link: '/services/' },
        { text: 'Global Fees Service', link: '/services/global-fees' },
        { text: 'AI Assistant', link: '/services/ai-assistant' },
      ],
    },
  ],
})
