import React, {useState} from "react";
import {createRoot} from "react-dom/client";
import {PagedList, WorkspaceViews} from "../src/components/WorkspaceViews";

/** Isolated list for testing wrapping, deletion and resize without business data. */
export function mountWorkspaceFixture() {
  document.getElementById("root")!.style.display="none";
  const element=document.createElement("main");element.className="app-shell";
  element.style.cssText="display:flex;height:100dvh;padding:24px;flex-direction:column";document.body.append(element);
  function Fixture(){
    const [filter,setFilter]=useState(0),[count,setCount]=useState(23);
    return <><header><button onClick={()=>setFilter(x=>1-x)}>筛选</button><button onClick={()=>setCount(x=>Math.max(0,x-1))}>删除末项</button></header><PagedList label="记录" resetKey={String(filter)}>{Array.from({length:filter?3:count},(_,i)=><article key={i} data-record={i} style={{padding:16,border:"1px solid #bbb",lineHeight:"24px"}}>{i===7?"带有较长知识名称和课程条件说明的记录，用于检查换行行高是否纳入分页测量。".repeat(5):"课程记录 "+i}</article>)}</PagedList></>;
  }
  createRoot(element).render(<Fixture/>);
}

/** JSX formatting whitespace must not become an empty task view. */
export function mountWorkspaceTabsFixture() {
  document.getElementById("root")!.style.display="none";
  const element=document.createElement("main");document.body.append(element);
  createRoot(element).render(<WorkspaceViews labels={["知识表现", "关注依据"]}>{"  "}<section>知识点状态内容</section>{"\n  "}<section>关注依据内容</section></WorkspaceViews>);
}
