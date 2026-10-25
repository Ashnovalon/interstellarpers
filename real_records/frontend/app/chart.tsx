'use client';
import {useEffect,useRef} from 'react';
import * as echarts from 'echarts';
export default function Chart({option,label}:{option:echarts.EChartsOption,label:string}){
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const element=ref.current;if(!element)return;
    const chart=echarts.init(element,undefined,{renderer:'svg'});chart.setOption(option);
    const observer=new ResizeObserver(()=>chart.resize());observer.observe(element);
    return()=>{observer.disconnect();chart.dispose()};
  },[option]);
  return <div className="chart" ref={ref} role="img" aria-label={label}/>;
}
