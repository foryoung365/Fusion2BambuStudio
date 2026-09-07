/* Per-attempt confirmation: cancel never replays an edit, confirm replays once. */
(function(root){'use strict';
class TransferConfirmation {
 constructor(dialog,message,accept,cancel,onConfirm){
  this.dialog=dialog;this.message=message;this.onConfirm=onConfirm;this.pending=null;
  accept.addEventListener('click',()=>this.confirm());
  cancel.addEventListener('click',()=>this.cancel());
  dialog.addEventListener('cancel',()=>{this.pending=null;});
 }
 open(transaction,text){this.pending={action:transaction.action,data:{...transaction.data}};this.message.textContent=text;this.dialog.showModal();}
 confirm(){const pending=this.pending;if(!pending)return;this.pending=null;this.dialog.close();this.onConfirm(pending.action,{...pending.data,confirmMixed:true});}
 cancel(){this.pending=null;this.dialog.close();}
}
if(typeof module!=='undefined'&&module.exports)module.exports=TransferConfirmation;else root.TransferConfirmation=TransferConfirmation;
})(typeof window!=='undefined'?window:globalThis);
