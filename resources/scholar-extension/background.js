async function deliver(payload){
  try{
    const response=await fetch('http://127.0.0.1:8787/api/scholar/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!response.ok)throw new Error((await response.json()).error||'拾光拒绝了快照');
    await chrome.storage.local.remove('pendingSnapshot');return {ok:true};
  }catch(error){await chrome.storage.local.set({pendingSnapshot:payload});return {ok:false,error:String(error.message||error)};}
}
chrome.runtime.onMessage.addListener((message,_sender,reply)=>{if(message.type==='sync-scholar'){deliver(message.payload).then(reply);return true}});
chrome.runtime.onStartup.addListener(async()=>{const {pendingSnapshot}=await chrome.storage.local.get('pendingSnapshot');if(pendingSnapshot)deliver(pendingSnapshot)});
