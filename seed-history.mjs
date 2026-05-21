import { initializeApp } from "firebase/app";
import { getFirestore, collection, addDoc } from "firebase/firestore";
import fs from "fs";

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
  const c = collection(db, "history");
  await addDoc(c, {
    month: 4,
    day: 30,
    event: "1939年4月30日、ニューヨーク万国博覧会が開幕。KodakやRCAなどの企業が最先端の映像・通信技術やカメラを展示し、カラー写真の普及に大きく貢献した。",
    url: "https://ja.wikipedia.org/wiki/1939%E5%B9%B4%E3%83%8B%E3%83%A5%E3%83%BC%E3%83%A8%E3%82%AF%E4%B8%87%E5%9B%BD%E5%8D%9A%E8%A6%A7%E4%BC%9A"
  });
  await addDoc(c, {
    month: 4,
    day: 30,
    event: "1904年4月30日、ルイジアナ・パーチェス・エキスポ（セントルイス万国博覧会）が開幕。早期の写真技術とステレオカメラによる立体写真が広く大衆の関心を集めた。",
    url: "https://ja.wikipedia.org/wiki/%E3%82%BB%E3%83%B3%E3%83%88%E3%83%AB%E3%82%A4%E3%82%B9%E4%B8%87%E5%9B%BD%E5%8D%9A%E8%A6%A7%E4%BC%9A"
  });
  await addDoc(c, {
    month: 4,
    day: 30,
    event: "主要なカメラ誌および風景写真誌において、春季（4月号・5月号）の特大号として「新緑・大型連休の撮影ガイド」が毎年この時期を境に一斉に発刊・特集される。",
    url: "https://www.google.com/search?q=%E9%A2%A8%E6%99%AF%E5%86%99%E7%9C%9F+%E6%96%B0%E7%B7%91+%E6%92%AE%E5%BD%B1%E3%82%AC%E3%82%A4%E3%83%89"
  });
  console.log("Seeded history for 4/30");
  process.exit(0);
}
run();
