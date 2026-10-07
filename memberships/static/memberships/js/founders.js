document.addEventListener('DOMContentLoaded', async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const tenantSlug = urlParams.get('org') || 'longevity-haus';

  const plansContainer = document.getElementById('plans-grid-root');
  const modalPlansContainer = document.getElementById('modal-plans-list');

  // 1. Fetch Dynamic Branding Tokens
  try {
    const brandResponse = await fetch(`/v1/public/branding?org=${tenantSlug}`);
    if (brandResponse.ok) {
      const brandData = await brandResponse.json();
      if (brandData.branding.accent_color) {
        document.documentElement.style.setProperty('--accent-gold', brandData.branding.accent_color);
      }
      if (brandData.branding.accent_hover) {
        document.documentElement.style.setProperty('--accent-gold-hover', brandData.branding.accent_hover);
      }
    }
  } catch (err) {
    console.error("Failed to load branding:", err);
  }

  // 2. Fetch Commercial Plans
  try {
    const plansResponse = await fetch(`/v1/public/plans?org=${tenantSlug}`);
    const plans = await plansResponse.json();

    // 2A. Render on Main Grid
    plansContainer.innerHTML = plans.map(plan => `
      <div class="plan-card">
        <div>
          <div class="plan-name">${plan.name}</div>
          <div class="plan-price">$${plan.rate_monthly}<span style="font-size:0.9rem; color:var(--text-muted)">/mo</span></div>
          <div class="plan-credits">${plan.credits_per_period} Biohacking Credits / mo</div>
          <div class="plan-allotment">${plan.allotments.perk || ''}</div>
        </div>
        <a href="/join/?org=${tenantSlug}&plan=${plan.id}" class="btn-tier-cta" style="text-align:center; text-decoration:none; display:block;">
          Lock Founding Rate ($${plan.deposit_amount})
        </a>
      </div>
    `).join('');

    // 2B. Render inside "CLAIM YOURS" Modal Popup
    if (modalPlansContainer) {
      modalPlansContainer.innerHTML = plans.map(plan => `
        <div style="background: var(--bg-surface); border: 1px solid var(--border-color); padding: 1.15rem; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; gap: 1rem; transition: border-color 0.2s;">
          <div>
            <div style="font-weight: 700; font-size: 1.05rem; color: var(--accent-gold);">${plan.name}</div>
            <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 0.2rem;">
              <strong>${plan.credits_per_period} Credits / mo</strong> &bull; ${plan.allotments.perk || ''}
            </div>
            <div style="font-size: 0.8rem; color: #7bf199; margin-top: 0.2rem;">
              $${plan.deposit_amount} refundable deposit applied to Month 1
            </div>
          </div>
          <div style="text-align: right; min-width: 140px;">
            <div style="font-size: 1.25rem; font-weight: 700; margin-bottom: 0.4rem;">$${plan.rate_monthly}<span style="font-size:0.75rem; color:var(--text-muted);">/mo</span></div>
            <a href="/join/?org=${tenantSlug}&plan=${plan.id}" style="background: var(--accent-gold); color: #000; padding: 0.45rem 0.9rem; text-decoration: none; font-size: 0.8rem; font-weight: bold; border-radius: 4px; display: inline-block;">
              Claim Pass &rarr;
            </a>
          </div>
        </div>
      `).join('');
    }

  } catch (err) {
    if (plansContainer) {
      plansContainer.innerHTML = '<p style="color:red;">Failed to retrieve membership tiers.</p>';
    }
  }
});