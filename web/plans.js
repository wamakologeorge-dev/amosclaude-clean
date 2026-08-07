(() => {
  const statusNode = document.querySelector('#status');
  const accessTimer = document.querySelector('#access-timer');
  const cashAppMethod = document.querySelector('#cash-app-method');
  const cashAppNote = document.querySelector('#cash-app-note');
  const bitcoinMethod = document.querySelector('#bitcoin-method');
  const bitcoinButton = document.querySelector('#bitcoin-button');
  const bitcoinNote = document.querySelector('#bitcoin-note');
  const priceNode = document.querySelector('#instant-price');
  const accessDaysNode = document.querySelector('#access-days');
  const manageButton = document.querySelector('#manage-button');
  let countdownTimer = null;
  let paymentPoll = null;
  let cashAppOrderId = '';

  const say = (message, error = false) => {
    statusNode.textContent = message || '';
    statusNode.style.color = error ? '#ff9ca8' : '#a9b4cb';
  };

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === 'string'
        ? payload.detail
        : 'Request could not be completed';
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  async function post(path, body) {
    return request(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  function stopCountdown() {
    if (countdownTimer) window.clearInterval(countdownTimer);
    countdownTimer = null;
  }

  function showCountdown(expiresAt) {
    stopCountdown();
    if (!expiresAt) {
      accessTimer.textContent = '';
      return;
    }
    const expiry = new Date(expiresAt).getTime();
    const render = () => {
      const seconds = Math.max(0, Math.floor((expiry - Date.now()) / 1000));
      const days = Math.floor(seconds / 86400);
      const hours = Math.floor((seconds % 86400) / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      accessTimer.textContent = seconds > 0
        ? `Full Package time remaining: ${days}d ${hours}h ${minutes}m`
        : 'Full Package timed access has expired.';
      if (seconds <= 0) stopCountdown();
    };
    render();
    countdownTimer = window.setInterval(render, 30000);
  }

  function openWorkspace(result) {
    const target = result?.redirect_url || '/cloud/agent?payment=activated';
    say('Payment confirmed. Amosclaud is opening the agent workspace…');
    showCountdown(result?.access_expires_at);
    window.setTimeout(() => window.location.assign(target), 1200);
  }

  async function pollOrder(orderId) {
    if (!orderId) return;
    window.localStorage.setItem('amosclaud_payment_order', orderId);
    if (paymentPoll) window.clearInterval(paymentPoll);

    let finished = false;
    const check = async () => {
      try {
        const result = await request(
          `/api/v1/billing/instant/orders/${encodeURIComponent(orderId)}`
        );
        if (result.access_active) {
          window.clearInterval(paymentPoll);
          paymentPoll = null;
          window.localStorage.removeItem('amosclaud_payment_order');
          finished = true;
          openWorkspace(result);
          return;
        }
        if (result.status === 'processing') {
          say('Payment received. Waiting for final provider confirmation…');
        } else if (result.status === 'failed') {
          window.clearInterval(paymentPoll);
          paymentPoll = null;
          window.localStorage.removeItem('amosclaud_payment_order');
          finished = true;
          say('The payment was not completed. Start a new checkout.', true);
        } else {
          say('Waiting for the payment provider to confirm your payment…');
        }
      } catch (error) {
        if (error.status === 401) {
          window.clearInterval(paymentPoll);
          paymentPoll = null;
          say('Sign in again before checking this payment.', true);
        }
      }
    };

    await check();
    if (!finished && !paymentPoll) paymentPoll = window.setInterval(check, 3000);
  }

  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${url}"]`);
      if (existing) {
        if (window.Square) resolve();
        else existing.addEventListener('load', resolve, {once: true});
        return;
      }
      const script = document.createElement('script');
      script.src = url;
      script.async = true;
      script.addEventListener('load', resolve, {once: true});
      script.addEventListener(
        'error',
        () => reject(new Error('Square payment library could not load')),
        {once: true}
      );
      document.head.appendChild(script);
    });
  }

  async function initializeCashApp(config) {
    if (!config.cash_app?.enabled) {
      cashAppMethod.classList.add('hidden');
      return;
    }
    try {
      const order = await post('/api/v1/billing/instant/cash-app/start');
      cashAppOrderId = order.order_id;
      await loadScript(config.cash_app.script_url);
      if (!window.Square) throw new Error('Square payment library is unavailable');

      const payments = window.Square.payments(
        config.cash_app.application_id,
        config.cash_app.location_id
      );
      const paymentRequest = payments.paymentRequest({
        countryCode: 'US',
        currencyCode: 'USD',
        total: {
          amount: config.amount,
          label: `Amosclaud Full Package — ${config.access_days} days`,
          pending: false,
        },
      });
      const cashAppPay = await payments.cashAppPay(paymentRequest, {
        redirectURL: window.location.href,
        referenceId: order.reference_id,
      });

      cashAppPay.addEventListener('ontokenization', async event => {
        const tokenResult = event.detail?.tokenResult || {};
        if (tokenResult.status === 'Cancel') {
          say('Cash App payment was cancelled.');
          return;
        }
        if (tokenResult.status !== 'OK' || !tokenResult.token) {
          say('Cash App could not authorize this payment.', true);
          return;
        }
        say('Cash App authorized. Confirming the payment securely…');
        try {
          const result = await post('/api/v1/billing/instant/cash-app/complete', {
            order_id: cashAppOrderId,
            source_id: tokenResult.token,
          });
          if (result.access_active) openWorkspace(result);
          else await pollOrder(cashAppOrderId);
        } catch (error) {
          say(error.message, true);
        }
      });

      await cashAppPay.attach('#cash-app-pay');
      cashAppNote.textContent = `Pay $${config.amount}. Access lasts ${config.access_days} days.`;
    } catch (error) {
      cashAppMethod.classList.add('hidden');
      say(error.message, true);
    }
  }

  async function startBitcoin() {
    bitcoinButton.disabled = true;
    say('Creating a unique Bitcoin invoice…');
    try {
      const result = await post('/api/v1/billing/instant/bitcoin/start');
      window.localStorage.setItem('amosclaud_payment_order', result.order_id);
      window.location.assign(result.url);
    } catch (error) {
      say(error.message, true);
      bitcoinButton.disabled = false;
    }
  }

  function showPlan(plan) {
    if (plan.plan !== 'full') return;
    say('Full Package is active.');
    showCountdown(plan.renews_at);
    manageButton.hidden = plan.source !== 'stripe';
  }

  document.querySelectorAll('[data-checkout]').forEach(button => {
    button.addEventListener('click', async () => {
      button.disabled = true;
      say('Opening secure subscription checkout…');
      try {
        const result = await post('/api/v1/billing/checkout', {
          interval: button.dataset.checkout,
        });
        window.location.assign(result.url);
      } catch (error) {
        say(error.message, true);
        button.disabled = false;
      }
    });
  });

  manageButton.addEventListener('click', async () => {
    try {
      const result = await post('/api/v1/billing/portal');
      window.location.assign(result.url);
    } catch (error) {
      say(error.message, true);
    }
  });

  document.querySelector('#license-form').addEventListener('submit', async event => {
    event.preventDefault();
    say('Activating license…');
    try {
      const result = await post('/api/v1/billing/license/activate', {
        key: document.querySelector('#license-key').value,
      });
      say('Full Package activated.');
      showPlan(result);
    } catch (error) {
      say(error.message, true);
    }
  });

  bitcoinButton.addEventListener('click', startBitcoin);

  (async () => {
    const query = new URLSearchParams(window.location.search);
    if (query.get('checkout') === 'success') {
      say('Payment received. Waiting for secure subscription confirmation…');
    }

    try {
      const config = await request('/api/v1/billing/instant/config');
      priceNode.textContent = config.amount;
      accessDaysNode.textContent = String(config.access_days);
      bitcoinButton.textContent = `Pay $${config.amount} in Bitcoin`;
      if (!config.bitcoin?.enabled) {
        bitcoinMethod.classList.add('hidden');
      } else {
        bitcoinNote.textContent = `Unique invoice for $${config.amount}. Access activates after settlement.`;
      }
      await initializeCashApp(config);
    } catch (error) {
      say(error.message, true);
      cashAppMethod.classList.add('hidden');
      bitcoinMethod.classList.add('hidden');
    }

    try {
      const plan = await request('/api/v1/billing/status');
      showPlan(plan);
    } catch (_) {
      // The page can still describe plans before sign-in.
    }

    const orderId = query.get('payment_order')
      || window.localStorage.getItem('amosclaud_payment_order');
    if (orderId) await pollOrder(orderId);
  })();
})();
