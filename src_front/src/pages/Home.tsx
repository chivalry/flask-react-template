export default function Home() {
  return (
    <main
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
        gap: "1rem",
      }}
    >
      <h1>Hello, World</h1>
      <p style={{ color: "#666" }}>
        Your Flask + React project starts here. Edit{" "}
        <code>src_front/src/pages/Home.tsx</code> to get going.
      </p>
    </main>
  );
}
