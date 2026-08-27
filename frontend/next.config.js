/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  env: {
    // The FastAPI backend. Localhost only -- the API has no auth yet.
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000",
  },
};
