import { defineConfig } from 'vocs'

export default defineConfig({
  vite: {
    server: {
      allowedHosts: ['onchaindivers.com'],
    },
  },
  title: 'OnchainDivers Examples',
  description: 'Executable examples for the OnchainDivers Solana, Polymarket, HyperLiquid, and Robinhood Chain indexers',
  topNav: [
    { text: 'Blog', link: 'https://onchaindivers.substack.com/' },
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
      text: 'Robinhood Chain Indexer',
      collapsed: false,
      items: [
        { text: 'Overview', link: '/robinhood/' },
        { text: 'Query Examples', link: '/robinhood/examples' },
        { text: 'Table Reference', link: '/robinhood/tables' },
      ],
    },
    {
      text: 'Research',
      collapsed: false,
      items: [
        { text: 'Reliable Pump.fun Creators', link: '/research/reliable-pumpfun-creators' },
        { text: 'Pump.fun Migration Programs', link: '/research/pumpfun-migration-parent-programs' },
        { text: 'Bitcoin 5m Cross-Venue', link: '/bitcoin-5m-cross-venue' },
        { text: 'Simple Microprice', link: '/microprice-research' },
      ],
    },
    { text: 'Fees API', link: '/fees-api' },
    {
      text: 'Solana Services',
      collapsed: false,
      items: [
        { text: 'Nodes & Low-Latency Feeds', link: '/solana-nodes' },
        { text: 'WSOL Exchange', link: '/services/wsol-exchange' },
      ],
    },
  ],
})
