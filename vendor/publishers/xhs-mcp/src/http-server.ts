/**
 * @fileoverview HTTP transport server for the MCP protocol.
 * Provides a Hono-based HTTP server as an alternative to stdio transport.
 * Uses StreamableHTTPServerTransport for MCP communication.
 * @module http-server
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { createServer } from 'node:http';
import { createMcpServer } from './server.js';
import { initDatabase } from './db/index.js';
import { getAccountPool } from './core/account-pool.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { config } from './core/config.js';

/**
 * Start the HTTP transport server for the MCP protocol.
 * Uses Hono as the HTTP framework and supports Node.js or Bun runtimes.
 *
 * @param port - Port number to listen on (default: 18060)
 */
export async function startHttpServer(port: number = config.server.port) {
  // Initialize database and account pool
  const db = await initDatabase();
  const pool = getAccountPool(db);

  /**
   * Create a new MCP server and transport for each request.
   * In stateless HTTP mode, each request is independent.
   */
  const getOrCreateServer = async (): Promise<{ server: Server; transport: StreamableHTTPServerTransport }> => {
    // For stateless mode, we need a fresh transport per request
    // but can potentially reuse the server logic
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined, // Stateless mode
      // The desktop app makes single request/response MCP calls. Returning JSON
      // here keeps the Node/Hono bridge from having to keep an SSE stream alive.
      enableJsonResponse: true,
    });

    // Create server if not exists, or create new one for each request in stateless mode
    // Note: In stateless HTTP mode, each request is independent
    const server = createMcpServer(pool, db);
    await server.connect(transport);

    return { server, transport };
  };

  const app = new Hono();

  // Enable CORS for all origins
  app.use(
    '*',
    cors({
      origin: '*',
      exposeHeaders: ['Mcp-Session-Id'],
    }),
  );

  // MCP endpoint using StreamableHTTPServerTransport
  app.post('/mcp', async (c) => {
    let server: Server | null = null;
    let transport: StreamableHTTPServerTransport | null = null;

    try {
      const result = await getOrCreateServer();
      server = result.server;
      transport = result.transport;

      // Get the raw request body
      const body = await c.req.json();

      // Create a mock Express-like request/response for the transport
      // StreamableHTTPServerTransport expects Express-style req/res
      const headers: Record<string, string> = {};
      c.req.raw.headers.forEach((value, key) => {
        headers[key] = value;
      });

      const mockReq = {
        headers,
        body,
        method: 'POST',
        url: '/mcp',
      };

      let responseBody: string | null = null;
      let responseHeaders: Record<string, string> = {};
      let responseStatus = 200;
      let headersSent = false;
      let responseEnded = false;
      let completeResponse: (() => void) | null = null;
      const responseCompleted = new Promise<void>((resolve) => {
        completeResponse = resolve;
      });
      const responseEvents = new Map<string, Array<(...args: any[]) => void>>();

      const appendResponseChunk = (chunk?: string | Buffer) => {
        if (chunk === undefined || chunk === null) return;
        if (responseBody === null) responseBody = '';
        responseBody += typeof chunk === 'string' ? chunk : chunk.toString();
      };

      const mockRes = {
        writeHead: (status: number, headers?: Record<string, string>) => {
          responseStatus = status;
          headersSent = true;
          if (headers) {
            responseHeaders = { ...responseHeaders, ...headers };
          }
          return mockRes;
        },
        setHeader: (name: string, value: string) => {
          responseHeaders[name] = value;
          return mockRes;
        },
        getHeader: (name: string) => responseHeaders[name],
        write: (chunk: string | Buffer) => {
          headersSent = true;
          appendResponseChunk(chunk);
          return true;
        },
        end: (data?: string | Buffer) => {
          appendResponseChunk(data);
          if (!responseEnded) {
            responseEnded = true;
            completeResponse?.();
            for (const listener of responseEvents.get('close') || []) listener();
          }
          return mockRes;
        },
        on: (event: string, listener: (...args: any[]) => void) => {
          const listeners = responseEvents.get(event) || [];
          listeners.push(listener);
          responseEvents.set(event, listeners);
          return mockRes;
        },
        get headersSent() {
          return headersSent;
        },
        flushHeaders: () => {},
      };

      await transport.handleRequest(mockReq as any, mockRes as any, body);
      // handleRequest schedules the MCP handler and returns before that handler
      // writes to ServerResponse. Wait for end(), just like Node's HTTP server.
      if (!responseEnded) {
        await Promise.race([
          responseCompleted,
          new Promise<void>((_, reject) => {
            setTimeout(() => reject(new Error('MCP response timed out')), 60000);
          }),
        ]);
      }

      // Build response
      const response = new Response(responseBody, {
        status: responseStatus,
        headers: responseHeaders,
      });

      return response;
    } catch (error) {
      console.error('Error handling MCP request:', error);
      return c.json(
        {
          jsonrpc: '2.0',
          error: {
            code: -32603,
            message: 'Internal server error',
          },
          id: null,
        },
        500,
      );
    } finally {
      // Clean up transport and server
      if (transport) {
        await transport.close().catch(() => {});
      }
      if (server) {
        await server.close().catch(() => {});
      }
    }
  });

  // Method not allowed for GET/DELETE
  app.get('/mcp', (c) => {
    return c.json(
      {
        jsonrpc: '2.0',
        error: {
          code: -32000,
          message: 'Method not allowed.',
        },
        id: null,
      },
      405,
    );
  });

  app.delete('/mcp', (c) => {
    return c.json(
      {
        jsonrpc: '2.0',
        error: {
          code: -32000,
          message: 'Method not allowed.',
        },
        id: null,
      },
      405,
    );
  });

  // Health check endpoint
  app.get('/health', (c) => {
    return c.json({ status: 'ok', server: 'xhs-mcp', version: '2.0.0' });
  });

  // Info endpoint
  app.get('/', (c) => {
    return c.json({
      name: 'xhs-mcp',
      version: '2.0.0',
      description: 'Xiaohongshu MCP Server with Multi-Account Support',
      endpoints: {
        mcp: '/mcp',
        health: '/health',
      },
    });
  });

  console.error(`Starting HTTP server on port ${port}...`);
  console.error(`MCP endpoint: http://localhost:${port}/mcp`);

  let nodeServer: ReturnType<typeof createServer> | null = null;

  // Graceful shutdown
  const shutdown = async () => {
    console.error('Shutting down HTTP server...');
    nodeServer?.close();
    await pool.closeAll();
    db.close();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  if (typeof Bun !== 'undefined') {
    Bun.serve({ port, fetch: app.fetch });
  } else {
    nodeServer = createServer(async (req, res) => {
      try {
        const chunks: Buffer[] = [];
        for await (const chunk of req) {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        }
        const method = req.method || 'GET';
        const headers = new Headers();
        for (const [name, value] of Object.entries(req.headers)) {
          if (Array.isArray(value)) headers.set(name, value.join(', '));
          else if (value !== undefined) headers.set(name, value);
        }
        const host = req.headers.host || `127.0.0.1:${port}`;
        const body = ['GET', 'HEAD'].includes(method) ? undefined : Buffer.concat(chunks);
        const response = await app.fetch(
          new Request(`http://${host}${req.url || '/'}`, { method, headers, body }),
        );
        const responseHeaders: Record<string, string> = {};
        response.headers.forEach((value, name) => {
          responseHeaders[name] = value;
        });
        res.writeHead(response.status, responseHeaders);
        res.end(Buffer.from(await response.arrayBuffer()));
      } catch (error) {
        console.error('Node HTTP request failed:', error);
        res.writeHead(500, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ error: 'Internal server error' }));
      }
    });
    nodeServer.listen(port);
  }

  console.error(`HTTP server running on http://localhost:${port}`);
}
