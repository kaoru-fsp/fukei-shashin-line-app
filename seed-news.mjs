import { initializeApp } from "firebase/app";
import { getFirestore, collection, addDoc } from "firebase/firestore";

const firebaseConfig = {
  apiKey: "AIzaSyAn4I5XBMPzggAXM0FsTZH9Ilxx96mZQe8",
  authDomain: "gen-lang-client-0328956131.firebaseapp.com",
  projectId: "gen-lang-client-0328956131",
  storageBucket: "gen-lang-client-0328956131.firebasestorage.app",
  messagingSenderId: "529174988876",
  appId: "1:529174988876:web:82e6d0595ce23fd19e4ce9"
};
const app = initializeApp(firebaseConfig);
const db = getFirestore(app);

async function run() {
  const c = collection(db, "news");
  const facts = [
    { headline: "気象庁：さくらの開花発表（札幌・函館エリア）", url: "https://www.jma.go.jp/jma/press/index.html", location: "北海道", date: "4月30日", category: "開花", dateStr: "2026-04-30" },
    { headline: "国土交通省：知床横断道路（国道334号）の冬期通行止め一部解除", url: "https://www.hkd.mlit.go.jp/", location: "北海道・知床", date: "4月28日〜", category: "交通", dateStr: "2026-04-30" },
    { headline: "気象庁：富士山の初雪・冠雪状況（最新観測データ）", url: "https://www.jma.go.jp/bosai/snow/", location: "山梨/静岡", date: "4月30日", category: "気象", dateStr: "2026-04-30" },
    { headline: "交通局：立山黒部アルペンルート 雪の大谷ウォーク開催中", url: "https://www.alpen-route.com/", location: "富山・立山", date: "4月15日〜6月25日", category: "行事", dateStr: "2026-04-30" },
    { headline: "自治体情報：角館のシダレザクラ 満開宣言", url: "https://tazawako-kakunodate.com/", location: "秋田・角館", date: "4月29日発表", category: "開花", dateStr: "2026-04-30" },
    { headline: "自治体情報：弘前公園さくらまつり 開催状況", url: "https://www.hirosakipark.jp/sakura/", location: "青森・弘前", date: "4月中旬〜5月初旬", category: "行事", dateStr: "2026-04-30" },
    { headline: "国土交通省：志賀草津高原ルート（国道292号）全線開通", url: "https://www.ktr.mlit.go.jp/", location: "群馬/長野", date: "4月25日〜", category: "交通", dateStr: "2026-04-30" },
    { headline: "気象庁：本州付近の黄砂に関する気象情報", url: "https://www.jma.go.jp/bosai/kousa/", location: "西日本・東日本", date: "4月30日", category: "気象", dateStr: "2026-04-30" },
  ];
  for (const fact of facts) {
    await addDoc(c, fact);
  }
  console.log("Seeded news");
  process.exit(0);
}
run();
