import React from 'react';

interface SalesCTAProps {
  price?: string;
  product?: string;
  formUrl?: string;
}

export function SalesCTA({
  price = '$200',
  product = 'Full Access',
  formUrl = 'https://forms.gle/b5Fuuns7jcA3nHKv5'
}: SalesCTAProps) {
  return (
    <div style={{
      marginTop: '3rem',
      padding: '1.5rem',
      borderRadius: '8px',
      border: '1px solid var(--vocs-color_border)',
      background: 'var(--vocs-color_background2)',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '1rem',
      }}>
        <div>
          <div style={{
            fontSize: '1.1rem',
            fontWeight: 600,
            color: 'var(--vocs-color_text)',
            marginBottom: '0.25rem',
          }}>
            {product} — {price}/month
          </div>
          <div style={{
            fontSize: '0.875rem',
            color: 'var(--vocs-color_text3)',
          }}>
            Unlimited queries · Direct support · Community access
          </div>
        </div>
        <a
          href={formUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.625rem 1.25rem',
            borderRadius: '6px',
            fontSize: '0.875rem',
            fontWeight: 600,
            textDecoration: 'none',
            background: 'var(--vocs-color_textAccent)',
            color: 'white',
            transition: 'opacity 0.15s',
          }}
        >
          Start Free Trial →
        </a>
      </div>
    </div>
  );
}

interface CommunityCTAProps {
  telegramUrl?: string;
  twitterUrl?: string;
}

export function CommunityCTA({
  telegramUrl = 'https://t.me/inventandchill',
  twitterUrl = 'https://x.com/AnyaInvent',
}: CommunityCTAProps) {
  return (
    <div style={{
      marginTop: '1.5rem',
      paddingTop: '1.5rem',
      borderTop: '1px solid var(--vocs-color_border)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: '1rem',
    }}>
      <span style={{
        fontSize: '0.875rem',
        color: 'var(--vocs-color_text3)',
      }}>
        Join traders already using our infrastructure
      </span>
      <div style={{
        display: 'flex',
        gap: '0.75rem',
      }}>
        <a
          href={telegramUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.375rem',
            padding: '0.5rem 0.875rem',
            borderRadius: '6px',
            fontSize: '0.8125rem',
            fontWeight: 500,
            textDecoration: 'none',
            color: 'var(--vocs-color_text2)',
            border: '1px solid var(--vocs-color_border)',
            transition: 'border-color 0.15s',
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
          </svg>
          Telegram
        </a>
        <a
          href={twitterUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.375rem',
            padding: '0.5rem 0.875rem',
            borderRadius: '6px',
            fontSize: '0.8125rem',
            fontWeight: 500,
            textDecoration: 'none',
            color: 'var(--vocs-color_text2)',
            border: '1px solid var(--vocs-color_border)',
            transition: 'border-color 0.15s',
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
          </svg>
          Twitter
        </a>
      </div>
    </div>
  );
}

export function CTASection(props: SalesCTAProps & CommunityCTAProps) {
  return (
    <>
      <SalesCTA {...props} />
      <CommunityCTA {...props} />
    </>
  );
}
