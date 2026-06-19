export default function Loading() {
  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px 24px",
        background: "#fbfcff",
      }}
    >
      <style>{"@keyframes pf-route-spin{to{transform:rotate(360deg)}}"}</style>
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: "50%",
          border: "3px solid #ece7dc",
          borderTopColor: "#ff6b35",
          animation: "pf-route-spin .8s linear infinite",
          marginBottom: 16,
        }}
      />
      <p style={{ fontFamily: "'IBM Plex Mono'", fontSize: 13.5, color: "#a8a294" }}>Loading…</p>
    </div>
  );
}
