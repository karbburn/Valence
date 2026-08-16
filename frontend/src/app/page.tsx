export default function Home() {
  return (
    <main className="min-h-screen bg-canvas text-[var(--c-text)] p-6 font-sans">
      <div className="max-w-[1680px] mx-auto space-y-4">
        <div className="flex items-center justify-between border-b border-[var(--c-border)] pb-4">
          <div className="flex items-center space-x-3">
            <div className="w-7 h-7 bg-white rounded-[4px] flex items-center justify-center p-1">
              <div className="w-full h-full bg-[#080c14] rounded-[2px]" />
            </div>
            <span className="font-bold text-[18px] tracking-[0.05em] text-[#f8fafc]">
              VALENCE
            </span>
          </div>
          <span className="font-mono text-[11px] text-[var(--c-accent)] bg-[var(--c-accent-subtle)] border border-[var(--c-accent-border)] px-2 py-1 rounded-[3px]">
            STAGE 17 SCAFFOLD
          </span>
        </div>
      </div>
    </main>
  )
}
