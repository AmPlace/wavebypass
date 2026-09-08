import assert from 'node:assert/strict'
import { before, after, afterEach, test } from 'node:test'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'

let dom, dir, Home, mount, flushPromises, ref, createPinia, setActivePinia, usePlayerStore, wrapper
const saved = new Map()
const originalFetch = globalThis.fetch
const response = body => ({ok:true,json:async()=>body})
const row = {station_id:'radio_fixture',name:'音乐新闻测试',country:'TW',group_name:'目录甲',metadata:{tag:'自定义'},sources:[{source_id:'source_fixture'}]}
before(async () => {
  dom = new JSDOM('<!doctype html><html><body></body></html>',{url:'http://localhost:5173/'})
  for (const key of ['window','document','navigator','Element','Node','SVGElement','HTMLElement','getComputedStyle']) {
    saved.set(key,Object.getOwnPropertyDescriptor(globalThis,key))
    Object.defineProperty(globalThis,key,{configurable:true,value:key==='window'?dom.window:dom.window[key]})
  }
  saved.set('ResizeObserver',Object.getOwnPropertyDescriptor(globalThis,'ResizeObserver'))
  globalThis.ResizeObserver=class{observe(){} disconnect(){}}
  ;({mount,flushPromises}=await import('@vue/test-utils'))
  ;({ref}=await import('vue'))
  ;({createPinia,setActivePinia}=await import('pinia'))
  ;({usePlayerStore}=await import('../../src/stores/player.js'))
  const {build}=await import('vite'); const {default:vue}=await import('@vitejs/plugin-vue')
  dir=await mkdtemp(path.join(tmpdir(),'waveflow-radio-home-'))
  await build({configFile:false,logLevel:'silent',plugins:[vue()],build:{outDir:dir,lib:{entry:new URL('../../src/views/Home.vue',import.meta.url).pathname,formats:['es'],fileName:()=> 'home.mjs'},rollupOptions:{external:['vue','pinia'],output:{paths:{vue:import.meta.resolve('vue'),pinia:import.meta.resolve('pinia')}}}}})
  Home=(await import(pathToFileURL(path.join(dir,'home.mjs')))).default
})
afterEach(()=>{wrapper?.unmount();wrapper=null;globalThis.fetch=originalFetch;document.body.innerHTML=''})
after(async()=>{dom?.window.close();for(const[key,d]of saved)d?Object.defineProperty(globalThis,key,d):delete globalThis[key];if(dir)await rm(dir,{recursive:true,force:true})})
function openHome(){
  const pinia=createPinia();setActivePinia(pinia)
  wrapper=mount(Home,{attachTo:document.body,global:{plugins:[pinia],provide:{searchQuery:ref(''),scrollRef:ref(document.body)},stubs:{TagFilterRow:{props:['items','isActive'],emits:['select'],template:'<div><button v-for="item in items" :key="item.value" @click="$emit(\'select\',item)">{{item.label}}</button></div>'}}}})
  return usePlayerStore()
}
const button = text => wrapper.findAll('button').find(b=>b.text()===text)

test('partial catalog failure is visible; retry reloads both catalogs and explicit filters keep authority',async()=>{
  let failStatic=true
  const calls=[]
  globalThis.fetch=async url=>{
    calls.push(String(url))
    if(String(url).endsWith('/api/stations'))return failStatic?{ok:false}:response([{id:'static',name:'内置',tags:['HK','news']}])
    return response({stations:[row],catalog_states:[]})
  }
  const store=openHome();await flushPromises()
  assert.match(wrapper.text(),/部分电台目录暂时不可用/)
  assert.equal(button('音乐'),undefined)
  assert.ok(button('自定义'))
  assert.deepEqual(wrapper.findAll('option').map(o=>o.text()),['全部分组','目录甲'])
  failStatic=false;await button('重试').trigger('click');await flushPromises()
  assert.equal(calls.filter(url=>url.endsWith('/api/stations')).length,2)
  assert.equal(calls.filter(url=>url.endsWith('/api/radio/stations')).length,2)
  assert.doesNotMatch(wrapper.text(),/部分电台目录暂时不可用/)
  await wrapper.get('select').setValue('目录甲')
  assert.equal(wrapper.findAll('.channel-card').length,1)
  await wrapper.get('.channel-card').trigger('click')
  assert.equal(store.currentStation,'radio_fixture')
  assert.equal(store.radioPlaybackIntent,'station_click')
  store.setLoading(false);await flushPromises()
  assert.equal(wrapper.get('.channel-card').classes().includes('channel-card-current'),true)
  store.togglePlay(false);await flushPromises()
  assert.equal(wrapper.get('.channel-card').classes().includes('channel-card-current'),false)
  assert.equal(wrapper.get('.channel-card').attributes('aria-current'),'true')
})

test('fast static catalog stays browsable while plugin request waits; unmount rejects late results',async()=>{
  let finish
  const signals=[]
  globalThis.fetch=async(url,options)=>{
    signals.push(options.signal)
    if(String(url).endsWith('/api/stations'))return response([{id:'static',name:'内置',tags:['HK']}])
    return new Promise(resolve=>{finish=resolve})
  }
  const store=openHome();await flushPromises()
  assert.equal(store.stationList.length,1)
  assert.match(wrapper.text(),/正在更新电台目录/)
  wrapper.unmount();wrapper=null
  assert.equal(signals[0].aborted,false)
  assert.equal(signals[1].aborted,true)
  finish(response({stations:[row]}));await flushPromises()
  assert.deepEqual(store.stationList.map(s=>s.id),['static'])
})

test('failed initial catalogs and valid empty catalogs are distinct and retryable',async()=>{
  let fail=true
  globalThis.fetch=async url=>fail?{ok:false}:response(String(url).endsWith('/api/stations')?[]:{stations:[]})
  openHome();await flushPromises()
  assert.match(wrapper.text(),/电台目录暂时无法加载/)
  fail=false;await button('重试加载').trigger('click');await flushPromises()
  assert.match(wrapper.text(),/暂无可用电台/)
  assert.doesNotMatch(wrapper.text(),/电台目录暂时无法加载/)
})
