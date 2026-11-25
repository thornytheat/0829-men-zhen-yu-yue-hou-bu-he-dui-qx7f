import {element} from './client.js';

function block(target,className,content) {
  const node=element('div',content,{class:className});
  target.append(node);
  return node;
}
const note=(target,text)=>block(target,'chart-note',text);

export function visualize(report,selected) {
  const target=document.querySelector('#visual');
  target.replaceChildren();
  const measurement=report.cases?.find(row=>row.case===selected)?.measure;
  if (!measurement) {block(target,'chart-note','选择有计算值的分组');return;}
  const e=measurement.evidence;

  const seats=block(target,'slot-tickets');
  for(const [slot,person] of Object.entries(e.occupied)) {
    const ticket=block(seats,'slot-ticket',`号源 ${slot}`);
    block(ticket,'slot-person',`编号 ${person}`);
    block(ticket,'slot-state',e.promoted[slot]?'候补转入':'原预约');
  }
  if(e.expired.length) note(target,`过期 ${e.expired.join('、')}`);
}
