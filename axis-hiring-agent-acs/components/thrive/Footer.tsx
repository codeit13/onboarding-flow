export function Footer() {
  return (
    <footer className="bg-axis-dark-footer text-white/80">
      {/* Main footer content */}
      <div className="max-w-7xl mx-auto px-6 py-10">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          {/* Brand column */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 bg-white rounded-sm flex items-center justify-center">
                <div className="w-4 h-4 bg-axis-burgundy rounded-sm rotate-45" />
              </div>
              <span className="font-bold tracking-wider text-sm text-white">AXIS BANK</span>
            </div>
            <p className="text-[12px] text-white/50 leading-relaxed">
              Axis Bank Ltd. is one of India&apos;s leading private sector banks, committed to
              building a high-performing, diverse workforce.
            </p>
          </div>

          {/* Quick links */}
          <div>
            <h4 className="text-[13px] font-semibold text-white mb-3">Careers</h4>
            <ul className="space-y-2 text-[12px] text-white/50">
              <li className="hover:text-white/80 cursor-pointer transition-colors">Browse open roles</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Life at Axis</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Campus hiring</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Diversity & inclusion</li>
            </ul>
          </div>

          {/* Support */}
          <div>
            <h4 className="text-[13px] font-semibold text-white mb-3">Support</h4>
            <ul className="space-y-2 text-[12px] text-white/50">
              <li className="hover:text-white/80 cursor-pointer transition-colors">Application FAQs</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Contact recruitment</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Accessibility</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Grievance redressal</li>
            </ul>
          </div>

          {/* Legal */}
          <div>
            <h4 className="text-[13px] font-semibold text-white mb-3">Legal</h4>
            <ul className="space-y-2 text-[12px] text-white/50">
              <li className="hover:text-white/80 cursor-pointer transition-colors">Privacy policy</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Terms of use</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Security statement</li>
              <li className="hover:text-white/80 cursor-pointer transition-colors">Disclaimer</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Bottom bar */}
      <div className="border-t border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-2">
          <p className="text-[11px] text-white/40">
            Copyright &copy; 2026 Axis Bank Ltd. All rights reserved.
          </p>
          <p className="text-[11px] text-white/40">
            Best viewed in latest version of Chrome, Firefox, Safari &amp; Edge
          </p>
        </div>
      </div>
    </footer>
  );
}
