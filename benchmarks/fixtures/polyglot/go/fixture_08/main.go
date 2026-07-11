package orders8

import "github.com/gin-gonic/gin"

type Store8 struct{}
func (s *Store8) Save() {}
type Service8 struct{ store *Store8 }
func (s *Service8) Create() { s.store.Save() }
type Handler8 struct{ service *Service8 }
func (h *Handler8) Handle() { h.service.Create() }
func Routes8(r *gin.Engine, h *Handler8) { r.GET("/orders/8", h.Handle) }
