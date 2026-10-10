import type { NextConfig } from 'next';
if (process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY === 'true' &&
    (process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY !== 'true' || process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL)) {
  throw new Error('Relay diagnostics require the canary gate and exclude the static STUN profile');
}

if (process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL && process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY !== 'true') {
  throw new Error('Diagnostic STUN requires NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY=true');
}

const nextConfig: NextConfig = {
  output: 'standalone',
  // Корень артефакта должен совпадать с приложением, даже если над checkout
  // лежит посторонний package-lock.json.
  outputFileTracingRoot: process.cwd(),
  typedRoutes: false,
  async rewrites() {
    // Прокси только в dev-окружении — в production используется NEXT_PUBLIC_API_BASE_URL
    if (process.env.NODE_ENV === 'production') {
      return [];
    }
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
