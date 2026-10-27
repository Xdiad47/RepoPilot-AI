# RepoPilot AI — frontend

Next.js 16 (App Router, Cache Components) · TypeScript · Tailwind CSS v4 · Radix Tabs · Lucide.

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm install
npm run dev                  # http://localhost:3000
npm run check                # lint + typecheck + tests + production build
```

Deploy to Vercel with **Root Directory = `frontend`** and `NEXT_PUBLIC_API_BASE_URL` set to the HTTPS backend URL.
See the root [README](../README.md) and [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).

Only public values may use the `NEXT_PUBLIC_` prefix: they are embedded in the browser bundle.
