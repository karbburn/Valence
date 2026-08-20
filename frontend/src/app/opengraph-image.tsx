import { ImageResponse } from 'next/og'

export const alt = 'Valence — Equity Valuation & Financial Modeling Workbench'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '72px',
          backgroundColor: '#080c14',
          color: '#f8fafc',
          fontFamily: 'sans-serif',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* Atmospheric glows */}
        <div
          style={{
            position: 'absolute',
            top: -220,
            right: -160,
            width: 720,
            height: 720,
            borderRadius: 720,
            backgroundImage:
              'radial-gradient(circle, rgba(14,165,233,0.45), rgba(14,165,233,0) 70%)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            bottom: -260,
            left: -160,
            width: 720,
            height: 720,
            borderRadius: 720,
            backgroundImage:
              'radial-gradient(circle, rgba(16,185,129,0.22), rgba(16,185,129,0) 70%)',
          }}
        />
        {/* Sharp brand accent bar */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            bottom: 0,
            width: 10,
            backgroundColor: '#0ea5e9',
          }}
        />

        {/* Top: wordmark + badge */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 8,
                backgroundColor: '#0ea5e9',
              }}
            />
            <div
              style={{
                fontSize: 40,
                fontWeight: 800,
                letterSpacing: 4,
                color: '#f8fafc',
              }}
            >
              VALENCE
            </div>
          </div>
          <div
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: '#0ea5e9',
              border: '1px solid rgba(14,165,233,0.4)',
              borderRadius: 999,
              padding: '10px 20px',
              backgroundColor: 'rgba(14,165,233,0.08)',
            }}
          >
            FREE · BROWSER-BASED
          </div>
        </div>

        {/* Headline */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
          }}
        >
          <div
            style={{
              fontSize: 78,
              fontWeight: 800,
              lineHeight: 1.05,
              color: '#f8fafc',
            }}
          >
            Institutional-Grade
          </div>
          <div
            style={{
              fontSize: 78,
              fontWeight: 800,
              lineHeight: 1.05,
              color: '#0ea5e9',
            }}
          >
            Valuation. In Your Browser.
          </div>
          <div
            style={{
              fontSize: 32,
              fontWeight: 500,
              color: '#94a3b8',
              marginTop: 10,
            }}
          >
            DCF · WACC · Trading Comps · 3-Statement Models for US & Indian Equities
          </div>
        </div>

        {/* Bottom: capability chips + domain */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', gap: 16 }}>
            {['30-tab Excel export', '9-point QA engine', 'US + India markets'].map(
              (chip) => (
                <div
                  key={chip}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    fontSize: 24,
                    fontWeight: 600,
                    color: '#cbd5e1',
                    border: '1px solid rgba(255,255,255,0.14)',
                    borderRadius: 12,
                    padding: '12px 20px',
                    backgroundColor: 'rgba(255,255,255,0.05)',
                  }}
                >
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 10,
                      backgroundColor: '#0ea5e9',
                    }}
                  />
                  {chip}
                </div>
              ),
            )}
          </div>
          <div style={{ fontSize: 24, fontWeight: 600, color: '#64748b' }}>
            valence-valuation.vercel.app
          </div>
        </div>
      </div>
    ),
    { ...size },
  )
}
