/** @type {import('next').NextConfig} */
// API traffic is deliberately not rewritten through Next.js.  Browser calls
// go directly to FastAPI so a slow, successful provider fallback cannot be
// terminated by the development proxy timeout.
const nextConfig = {}
module.exports = nextConfig
