import type {Metadata} from 'next';
import './style.css';
export const metadata:Metadata={title:'Pulp Riot | Import real records',description:'Real operational imports, forecasts and decisions'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
