import type { NextConfig } from 'next';
import path from 'node:path';
const config: NextConfig = {basePath:'/operations/real',output:'standalone',outputFileTracingRoot:path.resolve(__dirname),poweredByHeader:false};
export default config;
