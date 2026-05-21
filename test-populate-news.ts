import { db } from "./src/firebase";
import { collection, writeBatch, doc } from "firebase/firestore";

async function run() {
  const batch = writeBatch(db);
  batch.set(doc(collection(db, "history")), { event: "2012年、Nikon D800が発売された。高画素機ブームの先駆けとなる。", url: "" });
  batch.set(doc(collection(db, "ocean")), { headline: "本日の太平洋沿岸は穏やか。", location: "千葉県 九十九里", date: "2026-04-27" });
  batch.set(doc(collection(db, "news")), { headline: "春の桜前線が東北へ。奥入瀬渓流の新緑が見頃に。", location: "青森県", date: "2026-04-27" });
  await batch.commit();
  console.log("Done");
  process.exit(0);
}
run();
