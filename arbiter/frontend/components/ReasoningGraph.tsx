'use client'

import { useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  type Node,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { GraphNode, GraphEdge, RelationshipType } from '@/lib/types'

const EDGE_COLORS: Record<RelationshipType, string> = {
  SUPERSEDES: '#8b5cf6',
  OVERRIDE: '#f59e0b',
  EXCEPTION_TO: '#ef4444',
  REFERENCES: '#6b7280',
  CONFLICTS_WITH: '#dc2626',
  EXTENDS: '#3b82f6',
  DERIVED_FROM: '#10b981',
}

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export default function ReasoningGraph({ nodes, edges }: Props) {
  const rfNodes: Node[] = useMemo(
    () =>
      nodes.map((n, i) => ({
        id: n.node_id,
        type: 'default',
        position: {
          x: (i % 4) * 220 + 20,
          y: Math.floor(i / 4) * 110 + 20,
        },
        data: { label: n.label },
        style: {
          background: '#1a1a1a',
          border: '1px solid #3f3f46',
          color: '#e4e4e7',
          borderRadius: '8px',
          fontSize: '11px',
          padding: '6px 12px',
          maxWidth: 180,
        },
      })),
    [nodes]
  )

  const rfEdges: Edge[] = useMemo(
    () =>
      edges.map((e) => ({
        id: e.edge_id,
        source: e.source_id,
        target: e.target_id,
        label: e.relationship_type.replace(/_/g, ' '),
        animated: e.relationship_type === 'CONFLICTS_WITH',
        style: {
          stroke: EDGE_COLORS[e.relationship_type] ?? '#666',
          strokeWidth: 1.5,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: EDGE_COLORS[e.relationship_type] ?? '#666',
        },
        labelStyle: { fill: '#71717a', fontSize: 9 },
        labelBgStyle: { fill: '#09090b', fillOpacity: 0.8 },
      })),
    [edges]
  )

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      className="bg-neutral-950"
      proOptions={{ hideAttribution: true }}
    >
      <Background color="#27272a" gap={20} />
      <Controls
        style={{ background: '#18181b', border: '1px solid #3f3f46' }}
      />
    </ReactFlow>
  )
}
