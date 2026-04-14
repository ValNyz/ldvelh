'use client';

export default function AuthLayout({ children }) {
  return (
    <div className="min-h-screen bg-surface-container-lowest flex items-center justify-center p-4 relative overflow-hidden">
      {/* Atmospheric amber glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-[radial-gradient(ellipse,rgba(242,161,27,0.06)_0%,transparent_70%)] pointer-events-none" />
      {/* Vignette */}
      <div className="absolute inset-0 shadow-[inset_0_0_150px_rgba(0,0,0,0.5)] pointer-events-none" />

      <div className="w-full max-w-md relative z-10">
        <div className="text-center mb-8">
          <img
            alt="InkRealm Logo"
            className="h-16 w-auto object-contain mx-auto mb-4 amber-glow"
            src="/images/inkrealm.png"
          />
          <p className="text-on-surface-variant/60 text-xs uppercase tracking-[0.25em] font-label">
            Vivez les conséquences de vos choix
          </p>
        </div>
        {children}
      </div>
    </div>
  );
}
