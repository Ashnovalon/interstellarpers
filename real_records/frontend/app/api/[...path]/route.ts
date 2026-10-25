import {NextRequest,NextResponse} from 'next/server';
export const dynamic='force-dynamic';
const allowed=new Set(['health','contracts','validate','imports','records','state','train','scenarios','optimize','proposals','requests','history','services','monitoring']);
async function proxy(request:NextRequest,context:{params:Promise<{path:string[]}>}){
  if(process.env.REAL_RECORDS_TOKEN&&request.headers.get('authorization')!=='Bearer '+process.env.REAL_RECORDS_TOKEN)return NextResponse.json({detail:'Unauthorized'},{status:401});
  const {path}=await context.params;
  if(!allowed.has(path[0])||path.some(p=>p==='..'||p.includes('/')))return NextResponse.json({detail:'Unknown endpoint'},{status:404});
  const headers:Record<string,string>={'Content-Type':'application/json'};
  if(process.env.REAL_RECORDS_TOKEN)headers.Authorization='Bearer '+process.env.REAL_RECORDS_TOKEN;
  try{
    const response=await fetch((process.env.API_URL||'http://127.0.0.1:8010')+'/'+path.map(encodeURIComponent).join('/')+request.nextUrl.search,
      {method:request.method,headers,body:request.method==='GET'?undefined:await request.text(),cache:'no-store',signal:AbortSignal.timeout(180000)});
    return new NextResponse(await response.text(),{status:response.status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  }catch{return NextResponse.json({detail:'The real-records API is unavailable. Run scripts/start_real_records.ps1, then refresh.'},{status:503});}
}
export {proxy as GET,proxy as POST};
