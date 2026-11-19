import React from 'react';

export interface ExcelColdStartDropProps {
  stationId: string;
  onImportTables: (timingTableText: string, ioTableText?: string) => void;
  onRunDemoColdStart: () => void;
}

const ACCEPTED_FILE_EXT_RE = /\.(csv|tsv|txt|json)$/i;

function isSupportedTableFile(file: Pick<File, 'name' | 'type'>): boolean {
  if (ACCEPTED_FILE_EXT_RE.test(file.name)) return true;
  if (file.type === 'text/csv' || file.type === 'text/tab-separated-values' || file.type === 'text/plain' || file.type === 'application/json') {
    return true;
  }
  return false;
}

function isIoTableFileName(fileName: string): boolean {
  return /(^|[_\-\s])(io|eplan)([_\-\s.]|$)|端子|点表/i.test(fileName);
}

async function readDroppedFileText(file: File): Promise<string> {
  if (typeof file.text === 'function') {
    return file.text();
  }
  if (typeof FileReader !== 'undefined') {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
      reader.onerror = () => reject(reader.error ?? new Error('文件读取失败'));
      reader.readAsText(file);
    });
  }
  return '';
}

export function ExcelColdStartDrop({
  stationId,
  onImportTables,
  onRunDemoColdStart,
}: ExcelColdStartDropProps): React.ReactElement {
  const [isDragOver, setIsDragOver] = React.useState(false);
  const [isPasteOpen, setIsPasteOpen] = React.useState(false);
  const [timingText, setTimingText] = React.useState('');
  const [ioText, setIoText] = React.useState('');
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  async function processFiles(fileList: FileList | File[]): Promise<void> {
    const files = Array.from(fileList);
    if (files.length === 0) return;

    const supported = files.filter(isSupportedTableFile);
    if (supported.length === 0) {
      setStatusMessage('仅支持 .csv / .tsv / .txt / .json 表格文件');
      return;
    }

    try {
      const contents = await Promise.all(
        supported.map(async (f) => ({ name: f.name, text: await readDroppedFileText(f) }))
      );

      let nextTiming = timingText;
      let nextIo = ioText;

      if (contents.length === 1) {
        const [single] = contents;
        if (isIoTableFileName(single.name) && timingText.trim().length > 0) {
          nextIo = single.text;
        } else {
          nextTiming = single.text;
        }
      } else {
        for (const item of contents) {
          if (isIoTableFileName(item.name)) {
            nextIo = item.text;
          } else {
            nextTiming = item.text;
          }
        }
      }

      setTimingText(nextTiming);
      setIoText(nextIo);
      setStatusMessage(`已加载 ${contents.map((c) => c.name).join(' + ')}`);

      if (nextTiming.trim().length > 0) {
        onImportTables(nextTiming, nextIo.trim() || undefined);
      } else if (nextIo.trim().length > 0) {
        onImportTables('', nextIo);
      }
    } catch {
      setStatusMessage('读取表格文件失败，请检查文件编码后重试');
    }
  }

  function handleDragEnter(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setIsDragOver(true);
  }

  function handleDragOver(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    if (!isDragOver) setIsDragOver(true);
  }

  function handleDragLeave(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setIsDragOver(false);
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setIsDragOver(false);
    const files = event.dataTransfer?.files;
    if (files && files.length > 0) {
      void processFiles(files);
    }
  }

  function handleFileInputChange(event: React.ChangeEvent<HTMLInputElement>): void {
    const files = event.target.files;
    if (files && files.length > 0) {
      void processFiles(files);
    }
  }

  function handleSubmitPaste(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!timingText.trim() && !ioText.trim()) {
      setStatusMessage('请先粘贴《动作时序表》或《EPLAN IO表》内容');
      return;
    }
    setStatusMessage(null);
    onImportTables(timingText, ioText.trim() || undefined);
  }

  return (
    <section
      className="af5-coldstart-card af5-card"
      aria-label="多模态表格冷启动导入"
      data-station-id={stationId}
      style={{
        padding: '12px',
        borderRadius: '12px',
        backgroundColor: '#EEF2FF',
        border: '1px solid rgba(99, 102, 241, 0.28)',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        color: 'var(--ink-primary, #181816)',
        fontFamily: 'var(--font-sans, Inter, sans-serif)',
      }}
    >
      <div
        className="af5-coldstart-card__head"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
        }}
      >
        <span
          className="af5-coldstart-card__title"
          style={{ fontSize: '12px', fontWeight: 700, color: '#4338CA' }}
        >
          多模态表格冷启动
        </span>
        <span
          className="af5-coldstart-card__badge"
          style={{
            fontSize: '10px',
            fontFamily: 'var(--font-mono, monospace)',
            fontWeight: 700,
            padding: '2px 6px',
            borderRadius: '6px',
            backgroundColor: '#FFFFFF',
            color: '#4F46E5',
            border: '1px solid rgba(99, 102, 241, 0.22)',
          }}
        >
          AI PARSER · {stationId}
        </span>
      </div>

      <p
        className="af5-coldstart-card__desc"
        style={{
          margin: 0,
          fontSize: '11px',
          lineHeight: 1.5,
          color: 'var(--ink-secondary, #5C5A55)',
        }}
      >
        拖入或粘贴机械《动作时序表》与《EPLAN IO表》，同一执行器自动去重为唯一实例并生成虚影连线。
      </p>

      <div
        className={`af5-coldstart-dropzone${isDragOver ? ' af5-coldstart-dropzone--active' : ''}`}
        role="button"
        tabIndex={0}
        aria-label="拖拽表格文件到此处导入 (.csv / .tsv / .txt / .json)"
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        style={{
          border: isDragOver ? '1.5px dashed #4F46E5' : '1.5px dashed rgba(99, 102, 241, 0.45)',
          borderRadius: '10px',
          backgroundColor: isDragOver ? '#E0E7FF' : 'rgba(255, 255, 255, 0.85)',
          padding: '10px 8px',
          textAlign: 'center',
          fontSize: '11px',
          color: '#4338CA',
          cursor: 'pointer',
          transition: 'background-color 150ms ease, border-color 150ms ease',
        }}
      >
        <input
          ref={fileInputRef}
          className="af5-coldstart-file-input"
          type="file"
          accept=".csv,.tsv,.txt,.json"
          multiple
          onChange={handleFileInputChange}
          style={{ display: 'none' }}
        />
        <div style={{ fontWeight: 600 }}>拖放 .csv / .tsv / .txt / .json 至此</div>
        <div style={{ fontSize: '10px', color: '#6366F1', marginTop: '2px' }}>
          支持同时拖入时序表与 EPLAN IO 表
        </div>
      </div>

      {statusMessage && (
        <div
          className="af5-coldstart-card__status"
          style={{
            fontSize: '11px',
            color: '#4338CA',
            backgroundColor: 'rgba(255, 255, 255, 0.78)',
            borderRadius: '6px',
            padding: '4px 8px',
          }}
        >
          {statusMessage}
        </div>
      )}

      <div
        className="af5-coldstart-card__actions"
        style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}
      >
        <button
          type="button"
          className="af5-coldstart-btn af5-coldstart-btn--demo"
          onClick={onRunDemoColdStart}
          style={{
            width: '100%',
            padding: '7px 10px',
            borderRadius: '8px',
            border: 'none',
            backgroundColor: '#4F46E5',
            color: '#FFFFFF',
            fontSize: '12px',
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          一键导入时序表生成蓝图
        </button>

        <button
          type="button"
          className="af5-coldstart-btn af5-coldstart-btn--toggle"
          aria-expanded={isPasteOpen}
          onClick={() => setIsPasteOpen((prev) => !prev)}
          style={{
            width: '100%',
            padding: '5px 8px',
            borderRadius: '8px',
            border: '1px solid rgba(99, 102, 241, 0.3)',
            backgroundColor: '#FFFFFF',
            color: '#4338CA',
            fontSize: '11px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          {isPasteOpen ? '收起文本粘贴表单' : '粘贴《动作时序表》/《EPLAN IO表》'}
        </button>
      </div>

      {isPasteOpen && (
        <form
          className="af5-coldstart-paste-form"
          onSubmit={handleSubmitPaste}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
            paddingTop: '4px',
            borderTop: '1px solid rgba(99, 102, 241, 0.2)',
          }}
        >
          <label
            className="af5-coldstart-field"
            style={{ display: 'flex', flexDirection: 'column', gap: '3px', fontSize: '11px', fontWeight: 600 }}
          >
            <span>《动作时序表》(Excel TSV / CSV / Markdown / JSON)</span>
            <textarea
              aria-label="动作时序表文本"
              className="af5-coldstart-textarea af5-coldstart-textarea--timing"
              rows={4}
              value={timingText}
              onChange={(e) => setTimingText(e.target.value)}
              placeholder={'步号\t工步名称\t机构\t动作\t完成条件\n10\t气缸伸出\t压装气缸\t伸出下压\t动位磁开导通'}
              style={{
                width: '100%',
                padding: '6px 8px',
                borderRadius: '6px',
                border: '1px solid rgba(99, 102, 241, 0.35)',
                backgroundColor: '#FFFFFF',
                fontFamily: 'var(--font-mono, monospace)',
                fontSize: '11px',
                resize: 'vertical',
              }}
            />
          </label>

          <label
            className="af5-coldstart-field"
            style={{ display: 'flex', flexDirection: 'column', gap: '3px', fontSize: '11px', fontWeight: 600 }}
          >
            <span>《EPLAN IO表》(可选)</span>
            <textarea
              aria-label="EPLAN IO表文本"
              className="af5-coldstart-textarea af5-coldstart-textarea--io"
              rows={3}
              value={ioText}
              onChange={(e) => setIoText(e.target.value)}
              placeholder={'机构\t位号\t原位输入\t动位输入\t输出点\t电柜端子\n压装气缸\tDB_ST20_CylZ\t%I10.0\t%I10.1\t%Q10.0\tX10:01'}
              style={{
                width: '100%',
                padding: '6px 8px',
                borderRadius: '6px',
                border: '1px solid rgba(99, 102, 241, 0.35)',
                backgroundColor: '#FFFFFF',
                fontFamily: 'var(--font-mono, monospace)',
                fontSize: '11px',
                resize: 'vertical',
              }}
            />
          </label>

          <button
            type="submit"
            className="af5-coldstart-btn af5-coldstart-btn--submit"
            disabled={!timingText.trim() && !ioText.trim()}
            style={{
              padding: '6px 10px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: timingText.trim() || ioText.trim() ? '#4338CA' : '#A5B4FC',
              color: '#FFFFFF',
              fontSize: '11px',
              fontWeight: 700,
              cursor: timingText.trim() || ioText.trim() ? 'pointer' : 'not-allowed',
            }}
          >
            解析并生成虚影预览
          </button>
        </form>
      )}
    </section>
  );
}
